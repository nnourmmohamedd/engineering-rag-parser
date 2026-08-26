"""Ingestion orchestration: stage sequencing, gates, rollback and reconciliation.

Every pipeline stage is injected as a lightweight fake, so these tests run in
milliseconds and -- importantly -- never touch the real
``engineering_documents_v1`` collection or the real BM25 index. What is being
tested here is the *orchestration contract*: which stages run in what order,
what happens when each one fails, and whether the two indexes are left
consistent. The real pipelines have their own suites.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from engineering_rag.chatbot.config import ChatbotConfig, StorageConfig
from engineering_rag.chatbot.errors import ErrorCode
from engineering_rag.chatbot.ingestion import IngestionOrchestrator, ReconciliationReport
from engineering_rag.chatbot.models import DocumentRecord, IngestionJobRecord
from engineering_rag.chatbot.states import DocumentStatus, JobStage, JobState
from engineering_rag.chatbot.storage import Registry

pytestmark = pytest.mark.integration


class _Result:
    """Stands in for a ParserResult / chunk result / IndexingResult."""

    def __init__(self, run_dir: Path, status: str = "PASS") -> None:
        self.run_dir = run_dir
        self.status = status


class _FakeCollection:
    """An in-memory stand-in for a Chroma collection, scoped by document_id."""

    def __init__(self) -> None:
        self.records: dict[str, str] = {}  # chunk_id -> document_id

    def add_document(self, document_id: str, chunk_ids: list[str]) -> None:
        for cid in chunk_ids:
            self.records[cid] = document_id

    def get(self, where: dict[str, Any] | None = None, include: Any = None, ids: Any = None) -> dict:
        if where and "document_id" in where:
            wanted = where["document_id"]
            matched = [c for c, d in self.records.items() if d == wanted]
        else:
            matched = list(self.records)
        return {"ids": sorted(matched)}

    def delete(self, ids: list[str]) -> None:
        for cid in ids:
            self.records.pop(cid, None)


@pytest.fixture
def env(tmp_path: Path):
    """A fully isolated orchestrator: temp registry, temp storage, fake stages."""
    config = ChatbotConfig(storage=StorageConfig(root=tmp_path / "chatbot"))
    registry = Registry(config.storage.database_path)

    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF\n")

    document = registry.create_document(
        DocumentRecord(
            document_id="doc1",
            stored_filename="source.pdf",
            display_name="Source.pdf",
            sha256="a" * 64,
            media_type="application/pdf",
            byte_size=source.stat().st_size,
            parser_profile="default",
            source_path=str(source),
        )
    )
    registry.create_job(IngestionJobRecord(job_id="job1", document_id=document.document_id))

    collection = _FakeCollection()
    state: dict[str, Any] = {"calls": [], "collection": collection, "bm25": {}}

    def parser(pdf_path: Path, profile: str) -> _Result:
        state["calls"].append("parse")
        run = tmp_path / "parser_run"
        run.mkdir(exist_ok=True)
        return _Result(run)

    def chunker(parser_run_dir: Path) -> _Result:
        state["calls"].append("chunk")
        run = tmp_path / "chunk_run"
        run.mkdir(exist_ok=True)
        return _Result(run)

    def indexer(chunk_run_dir: Path) -> _Result:
        state["calls"].append("index")
        collection.add_document("doc1", ["c1", "c2", "c3"])
        return _Result(chunk_run_dir)

    def bm25() -> dict:
        state["calls"].append("bm25")
        # Mirrors the real builder: BM25 is rebuilt wholesale from Chroma.
        state["bm25"] = dict(collection.records)
        return {"corpus_count": len(state["bm25"])}

    orchestrator = IngestionOrchestrator(
        config=config,
        registry=registry,
        parser_runner=parser,
        chunker_runner=chunker,
        indexer_runner=indexer,
        bm25_builder=bm25,
        chroma_opener=lambda: collection,
    )
    # Reconciliation reads BM25 through the real loader in production; here it
    # reads the fake mirror the fake builder wrote.
    orchestrator.reconcile = lambda document_id: ReconciliationReport(  # type: ignore[method-assign]
        document_id=document_id,
        chroma_chunk_ids=sorted(c for c, d in collection.records.items() if d == document_id),
        bm25_chunk_ids=sorted(c for c, d in state["bm25"].items() if d == document_id),
        missing_from_bm25=sorted(
            {c for c, d in collection.records.items() if d == document_id}
            - {c for c, d in state["bm25"].items() if d == document_id}
        ),
        missing_from_chroma=sorted(
            {c for c, d in state["bm25"].items() if d == document_id}
            - {c for c, d in collection.records.items() if d == document_id}
        ),
    )
    orchestrator._snapshot_bm25 = lambda document_id: None  # type: ignore[method-assign]
    orchestrator._restore_bm25 = lambda snapshot: state.update(bm25={})  # type: ignore[method-assign]

    yield orchestrator, registry, state, config
    registry.close()


class TestHappyPath:
    def test_all_stages_run_in_order(self, env) -> None:
        orchestrator, _registry, state, _config = env
        outcome = orchestrator.run(document_id="doc1", job_id="job1")

        assert outcome.succeeded is True
        assert state["calls"] == ["parse", "chunk", "index", "bm25"]

    def test_document_becomes_ready_with_its_chunk_count(self, env) -> None:
        orchestrator, registry, _state, _config = env
        orchestrator.run(document_id="doc1", job_id="job1")

        document = registry.get_document("doc1")
        assert document.status is DocumentStatus.READY
        assert document.total_chunks == 3

    def test_job_finishes_ready_at_full_progress(self, env) -> None:
        orchestrator, registry, _state, _config = env
        orchestrator.run(document_id="doc1", job_id="job1")

        job = registry.get_job("job1")
        assert job.state is JobState.READY
        assert job.progress == 1.0
        assert job.finished_at is not None
        assert job.error_code is None

    def test_stage_timings_are_recorded_for_every_stage(self, env) -> None:
        orchestrator, registry, _state, _config = env
        orchestrator.run(document_id="doc1", job_id="job1")

        stages = {t.stage for t in registry.get_job("job1").stage_timings}
        assert {JobStage.PARSING, JobStage.CHUNKING, JobStage.VECTOR_INDEXING} <= stages

    def test_progress_events_are_emitted_in_order(self, env) -> None:
        orchestrator, _registry, _state, _config = env
        events: list[dict] = []
        orchestrator.run(document_id="doc1", job_id="job1", on_event=events.append)

        stage_events = [e["stage"] for e in events if e["type"] == "stage"]
        assert stage_events.index("PARSING") < stage_events.index("CHUNKING")
        assert stage_events.index("CHUNKING") < stage_events.index("VECTOR_INDEXING")
        assert events[-1]["type"] == "terminal"
        assert events[-1]["state"] == "READY"

    def test_reported_progress_is_monotonic(self, env) -> None:
        orchestrator, _registry, _state, _config = env
        events: list[dict] = []
        orchestrator.run(document_id="doc1", job_id="job1", on_event=events.append)

        progress = [e["progress"] for e in events if e["type"] == "stage"]
        assert progress == sorted(progress), "progress must never go backwards"


class TestStageFailures:
    """Every stage's failure must stop the pipeline and leave nothing searchable."""

    @pytest.mark.parametrize(
        ("attribute", "reached_stage"),
        [
            ("_parser_runner", JobStage.PARSING),
            ("_chunker_runner", JobStage.CHUNKING),
            ("_indexer_runner", JobStage.VECTOR_INDEXING),
            ("_bm25_builder", JobStage.BM25_INDEXING),
        ],
    )
    def test_a_raising_stage_fails_the_job_without_activating(
        self, env, attribute: str, reached_stage: JobStage
    ) -> None:
        orchestrator, registry, _state, _config = env

        def explode(*args, **kwargs):
            raise RuntimeError(f"{attribute} exploded")

        setattr(orchestrator, attribute, explode)
        outcome = orchestrator.run(document_id="doc1", job_id="job1")

        assert outcome.succeeded is False
        assert registry.get_document("doc1").status is DocumentStatus.FAILED
        job = registry.get_job("job1")
        assert job.state is JobState.FAILED
        # The stage that actually failed is retained, which is what the UI
        # shows and what a retry needs in order to explain itself.
        assert job.stage is reached_stage
        # An unrecognised library exception must become the generic code
        # rather than leaking its own type or message.
        assert job.error_code == ErrorCode.INTERNAL_ERROR

    def test_a_failed_parser_gate_stops_before_chunking(self, env) -> None:
        orchestrator, registry, state, _config = env
        orchestrator._parser_runner = lambda p, prof: _Result(Path("x"), status="FAIL")

        outcome = orchestrator.run(document_id="doc1", job_id="job1")

        assert outcome.succeeded is False
        assert outcome.error_code == ErrorCode.PARSER_VALIDATION_FAILED
        assert "chunk" not in state["calls"], "chunking must not run after a failed parser gate"

    def test_a_failed_chunk_gate_stops_before_indexing(self, env) -> None:
        orchestrator, _registry, state, _config = env
        orchestrator._chunker_runner = lambda d: _Result(Path("x"), status="FAIL")

        outcome = orchestrator.run(document_id="doc1", job_id="job1")

        assert outcome.error_code == ErrorCode.CHUNK_VALIDATION_FAILED
        assert "index" not in state["calls"], "indexing must not run after a failed chunk gate"

    def test_failure_evidence_is_preserved_for_retry(self, env) -> None:
        orchestrator, registry, _state, _config = env
        orchestrator._chunker_runner = lambda d: _Result(Path("x"), status="FAIL")
        orchestrator.run(document_id="doc1", job_id="job1")

        job = registry.get_job("job1")
        assert job.error_code == ErrorCode.CHUNK_VALIDATION_FAILED
        assert job.error_message
        assert job.stage is JobStage.CHUNK_VALIDATION

    def test_error_messages_never_leak_internals(self, env) -> None:
        orchestrator, registry, _state, _config = env

        def explode(*args, **kwargs):
            raise RuntimeError("/absolute/secret/path/leaked.py line 42")

        orchestrator._parser_runner = explode
        orchestrator.run(document_id="doc1", job_id="job1")

        message = registry.get_job("job1").error_message or ""
        assert "secret" not in message
        assert "/absolute" not in message


class TestRollback:
    """A failure after the Chroma write must undo it, not leave orphan chunks."""

    def test_bm25_failure_rolls_back_the_chroma_write(self, env) -> None:
        orchestrator, _registry, state, _config = env

        def explode():
            raise RuntimeError("bm25 build failed")

        orchestrator._bm25_builder = explode
        outcome = orchestrator.run(document_id="doc1", job_id="job1")

        assert outcome.succeeded is False
        assert state["collection"].records == {}, "partial Chroma records must be removed"

    def test_reconciliation_mismatch_rolls_back_and_does_not_activate(self, env) -> None:
        orchestrator, registry, state, _config = env
        # BM25 silently indexes only part of the document -> the indexes disagree.
        orchestrator._bm25_builder = lambda: state.update(bm25={"c1": "doc1"})

        outcome = orchestrator.run(document_id="doc1", job_id="job1")

        assert outcome.succeeded is False
        assert outcome.error_code == ErrorCode.INDEX_VALIDATION_FAILED
        assert registry.get_document("doc1").status is not DocumentStatus.READY
        assert state["collection"].records == {}

    def test_rollback_only_removes_the_failing_document(self, env) -> None:
        """One document's failure must never destroy the existing validated corpus."""
        orchestrator, _registry, state, _config = env
        state["collection"].add_document("other-doc", ["x1", "x2"])

        orchestrator._bm25_builder = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        orchestrator.run(document_id="doc1", job_id="job1")

        assert set(state["collection"].records) == {"x1", "x2"}

    def test_failure_before_the_chroma_write_needs_no_rollback(self, env) -> None:
        orchestrator, _registry, state, _config = env
        orchestrator._parser_runner = lambda p, prof: (_ for _ in ()).throw(RuntimeError("boom"))

        orchestrator.run(document_id="doc1", job_id="job1")
        assert state["collection"].records == {}


class TestCancellation:
    def test_cancellation_between_stages_stops_the_job(self, env) -> None:
        orchestrator, registry, state, _config = env

        def parser_then_cancel(pdf_path: Path, profile: str) -> _Result:
            state["calls"].append("parse")
            registry.update_job("job1", cancel_requested=True)
            run = Path(pdf_path).parent / "parser_run"
            run.mkdir(exist_ok=True)
            return _Result(run)

        orchestrator._parser_runner = parser_then_cancel
        outcome = orchestrator.run(document_id="doc1", job_id="job1")

        assert outcome.succeeded is False
        assert outcome.error_code == ErrorCode.INGESTION_CANCELLED
        assert registry.get_job("job1").state is JobState.CANCELLED
        assert "index" not in state["calls"]

    def test_cancellation_is_retryable(self, env) -> None:
        orchestrator, registry, _state, _config = env
        registry.update_job("job1", cancel_requested=True)
        orchestrator.run(document_id="doc1", job_id="job1")

        assert registry.get_job("job1").retryable is True


class TestIdempotentRetry:
    def test_a_successful_rerun_converges_on_the_same_state(self, env) -> None:
        orchestrator, registry, state, config = env
        orchestrator.run(document_id="doc1", job_id="job1")
        first_chunks = registry.get_document("doc1").total_chunks

        retry = registry.create_job(IngestionJobRecord(job_id="job2", document_id="doc1", attempt=2))
        outcome = orchestrator.run(document_id="doc1", job_id=retry.job_id)

        assert outcome.succeeded is True
        assert registry.get_document("doc1").total_chunks == first_chunks
        assert len(state["collection"].records) == 3, "a retry must not duplicate chunks"


class TestMissingSource:
    def test_a_vanished_source_file_fails_cleanly(self, env, tmp_path: Path) -> None:
        orchestrator, registry, _state, _config = env
        Path(registry.get_document("doc1").source_path).unlink()

        outcome = orchestrator.run(document_id="doc1", job_id="job1")
        assert outcome.succeeded is False
        assert registry.get_document("doc1").status is DocumentStatus.FAILED


class TestReconciliationReport:
    def test_consistent_requires_agreement_and_non_empty(self) -> None:
        assert ReconciliationReport("d", ["c1"], ["c1"], [], []).consistent is True
        assert ReconciliationReport("d", ["c1"], [], ["c1"], []).consistent is False
        assert ReconciliationReport("d", [], [], [], []).consistent is False, (
            "an empty document is not a successfully indexed one"
        )

    def test_report_serialises_counts_for_the_ui(self) -> None:
        report = ReconciliationReport("d", ["c1", "c2"], ["c1"], ["c2"], [])
        payload = report.as_dict()
        assert payload["chroma_chunk_count"] == 2
        assert payload["bm25_chunk_count"] == 1
        assert payload["consistent"] is False

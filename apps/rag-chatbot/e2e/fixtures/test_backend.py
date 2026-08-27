"""Controlled test backend for Playwright E2E tests.

Runs the real FastAPI application (`engineering_rag.chatbot.app.create_app`)
with the real registry, the real ingestion-state-machine worker, and the
real IngestionOrchestrator's sequencing/rollback logic -- but with the heavy
per-stage work faked: no Docling conversion, no BGE embedding model, no
Ollama server. Every stage transition the E2E tests observe (QUEUED ->
VALIDATING -> PARSING -> ... -> READY) is therefore genuinely emitted by the
real state machine and worker, not scripted by the test.

An in-process fake Chroma-like collection and a real (but tiny, in-memory)
answering fake stand in for the two genuinely heavy dependencies:

- The fake collection implements exactly the subset of the chromadb
  Collection API the orchestrator's reconciliation/rollback code calls
  (`get(where=..., include=...)`, `delete(ids=...)`), so
  `databases.chroma.list_document_chunk_ids`/`delete_document_records` work
  unmodified against it.
- `ask_runner` returns a real, schema-shaped answer for an "ordinary"
  question and a real refusal for a question containing "unsupported",
  exercising the actual AnswerOutcome mapping in
  `chatbot.answering.GroundedAnsweringService` without a real LLM call.

This mirrors the project's existing pattern (see
`tests/integration/chatbot/test_ingestion_orchestration.py`): fakes replace
external systems, never the orchestration logic itself.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "src"))

from engineering_rag.chatbot.answering import GroundedAnsweringService  # noqa: E402
from engineering_rag.chatbot.app import create_app  # noqa: E402
from engineering_rag.chatbot.config import ChatbotConfig, ServerConfig, StorageConfig  # noqa: E402
from engineering_rag.chatbot.ingestion import IngestionOrchestrator, ReconciliationReport  # noqa: E402
from engineering_rag.chatbot.storage import Registry  # noqa: E402
from engineering_rag.chatbot.worker import IngestionWorker  # noqa: E402


class _Result:
    """Stands in for a ParserResult / chunk result / IndexingResult."""

    def __init__(self, run_dir: Path, status: str = "PASS") -> None:
        self.run_dir = run_dir
        self.status = status


class FakeCollection:
    """An in-memory stand-in for a Chroma collection, scoped by document_id."""

    def __init__(self) -> None:
        self.records: dict[str, str] = {}

    def add_document(self, document_id: str, chunk_ids: list[str]) -> None:
        for chunk_id in chunk_ids:
            self.records[chunk_id] = document_id

    def get(self, where: dict[str, Any] | None = None, include: Any = None, ids: Any = None) -> dict:
        if where and "document_id" in where:
            wanted = where["document_id"]
            matched = [c for c, d in self.records.items() if d == wanted]
        else:
            matched = list(self.records)
        return {"ids": sorted(matched)}

    def delete(self, ids: list[str]) -> None:
        for chunk_id in ids:
            self.records.pop(chunk_id, None)

    def count(self) -> int:
        return len(self.records)


def _fake_ask_runner(query: str, *, retrieval_mode: str, metadata_filters: dict, top_k: int | None):
    """A schema-shaped fake answer, exercising the real AnswerOutcome mapping."""

    class _Citation:
        citation_id = "S1"
        chunk_id = "chunk_1"
        document_id = (
            (metadata_filters.get("document_id") or [None])[0]
            if isinstance(metadata_filters.get("document_id"), list)
            else metadata_filters.get("document_id")
        )
        source_filename = "sample.pdf"
        page_numbers = [1]
        section_title = "Introduction"
        supporting_quote = "This is a sample engineering document used for end-to-end testing."
        content_hash = "hash1"

    class _Validation:
        status = "PASS"
        checks_passed = ["no_unknown_citations", "has_inline_citation", "supporting_quotes_verified"]
        checks_failed: list[str] = []
        warnings: list[str] = []
        citation_coverage_ratio = 1.0
        repair_attempted = False

    class _AnsweredResponse:
        status = "answered"
        answer = "This is a sample engineering document used for end-to-end testing [S1]."
        citations = [_Citation()]
        validation = _Validation()
        stage_latencies_s = {"retrieval": 0.05, "generation": 0.2}
        model_tag = "fake-e2e-model"
        model_digest = "e2e0000"
        total_latency_s = 0.3

    class _RefusalValidation:
        status = "PASS"
        checks_passed: list[str] = []
        checks_failed: list[str] = []
        warnings: list[str] = []
        citation_coverage_ratio = None
        repair_attempted = False

    class _RefusalResponse:
        status = "insufficient_evidence"
        answer = "I could not find enough evidence in the indexed documents to answer this question reliably."
        citations: list[Any] = []
        validation = _RefusalValidation()
        stage_latencies_s = {"retrieval": 0.05}
        model_tag = "fake-e2e-model"
        model_digest = "e2e0000"
        total_latency_s = 0.1

    time.sleep(0.05)  # a tiny, real delay so the UI's loading state is observable
    if "unsupported" in query.lower():
        return (None, None, _RefusalResponse(), None, None)
    return (None, None, _AnsweredResponse(), None, None)


def build_app(data_root: Path, host: str, port: int, cors_origin: str):
    # The real /documents/{id}/preview endpoint reads Markdown from
    # `config.parser_output_root / parser_run_id` -- it must be the same
    # directory the fake parser_runner below actually writes into, or the
    # preview silently comes back empty even though ingestion succeeded.
    run_root = data_root / "fake_runs"
    run_root.mkdir(parents=True, exist_ok=True)
    config = ChatbotConfig(
        storage=StorageConfig(root=data_root),
        server=ServerConfig(host=host, port=port, cors_origins=[cors_origin]),
        parser_output_root=run_root,
        chunker_output_root=run_root,
    )
    registry = Registry(config.storage.database_path)
    collection = FakeCollection()

    def parser_runner(pdf_path: Path, profile: str) -> _Result:
        run_dir = run_root / f"parser_{int(time.time() * 1000)}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "document.md").write_text(
            "# Sample Engineering Document\n\n"
            "This is a sample engineering document used for end-to-end testing.\n\n"
            "## Section 1\n\nIt contains enough text to exercise the preview panel.\n",
            encoding="utf-8",
        )
        time.sleep(0.3)  # observable PARSING stage
        return _Result(run_dir)

    def chunker_runner(parser_run_dir: Path) -> _Result:
        run_dir = run_root / f"chunk_{int(time.time() * 1000)}"
        run_dir.mkdir(parents=True, exist_ok=True)
        time.sleep(0.3)  # observable CHUNKING stage
        return _Result(run_dir)

    _pending_document_id: dict[str, str] = {}

    def indexer_runner(chunk_run_dir: Path) -> _Result:
        # Real chunk records are keyed by the source file's SHA-256 (the
        # pipeline's own document identity, see services/chunker/ids.py),
        # not by this registry's document id -- reconcile()/rollback_document()
        # both key off it too, so this fake must mirror that or every
        # reconciliation fails and no document ever reaches READY.
        document_id = _pending_document_id.get("current", "unknown")
        record = registry.get_document(document_id)
        sha256 = record.sha256 if record is not None else document_id
        collection.add_document(sha256, [f"{sha256}_c1", f"{sha256}_c2", f"{sha256}_c3"])
        time.sleep(0.3)  # observable VECTOR_INDEXING stage
        return _Result(chunk_run_dir)

    def bm25_builder():
        time.sleep(0.2)  # observable BM25_INDEXING stage
        return {"corpus_count": collection.count()}

    def chroma_opener():
        return collection

    class TrackingOrchestrator(IngestionOrchestrator):
        def run(self, *, document_id: str, job_id: str, on_event=None):  # type: ignore[override]
            _pending_document_id["current"] = document_id
            return super().run(document_id=document_id, job_id=job_id, on_event=on_event)

        def reconcile(self, document_id: str) -> ReconciliationReport:  # type: ignore[override]
            ids = sorted(c for c, d in collection.records.items() if d == document_id)
            return ReconciliationReport(
                document_id=document_id,
                chroma_chunk_ids=ids,
                bm25_chunk_ids=ids,
                missing_from_bm25=[],
                missing_from_chroma=[],
            )

        def _snapshot_bm25(self, document_id: str):  # type: ignore[override]
            return None

        def _restore_bm25(self, snapshot) -> None:  # type: ignore[override]
            return None

    orchestrator = TrackingOrchestrator(
        config=config,
        registry=registry,
        parser_runner=parser_runner,
        chunker_runner=chunker_runner,
        indexer_runner=indexer_runner,
        bm25_builder=bm25_builder,
        chroma_opener=chroma_opener,
    )
    worker = IngestionWorker(config=config, registry=registry, orchestrator=orchestrator)
    answering = GroundedAnsweringService(config=config, registry=registry, ask_runner=_fake_ask_runner)

    return create_app(
        config,
        registry=registry,
        worker=worker,
        answering=answering,
        orchestrator=orchestrator,
    )


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("E2E_BACKEND_HOST", "127.0.0.1")
    port = int(os.environ.get("E2E_BACKEND_PORT", "8811"))
    cors_origin = os.environ.get("E2E_FRONTEND_ORIGIN", "http://127.0.0.1:4311")
    data_root = Path(
        os.environ.get("E2E_DATA_ROOT", REPO_ROOT / "apps" / "rag-chatbot" / "e2e" / ".tmp-data")
    )
    data_root.mkdir(parents=True, exist_ok=True)

    app = build_app(data_root, host, port, cors_origin)
    uvicorn.run(app, host=host, port=port, log_level="warning")

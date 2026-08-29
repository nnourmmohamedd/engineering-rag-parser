"""HTTP API: contracts, validation, error envelopes and selection isolation.

Runs against the real FastAPI application with the registry pointed at a
temporary directory and the heavy collaborators (ingestion worker, answering
pipeline) injected as fakes. Nothing here loads a model, converts a PDF or
touches the real ``engineering_documents_v1`` collection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from engineering_rag.chatbot.answering import AnswerOutcome, GroundedAnsweringService
from engineering_rag.chatbot.app import API_PREFIX, create_app
from engineering_rag.chatbot.config import ChatbotConfig, StorageConfig
from engineering_rag.chatbot.errors import ErrorCode
from engineering_rag.chatbot.models import DocumentRecord, IngestionJobRecord
from engineering_rag.chatbot.states import DocumentStatus, JobState
from engineering_rag.chatbot.storage import Registry
from engineering_rag.chatbot.worker import IngestionWorker

pytestmark = pytest.mark.integration

MINIMAL_PDF = b"%PDF-1.4\n%%EOF\n"


class _StubWorker(IngestionWorker):
    """Records submissions instead of running real ingestion."""

    def __init__(self, config: ChatbotConfig, registry: Registry) -> None:
        super().__init__(config=config, registry=registry)
        self.submitted: list[str] = []

    def start(self) -> None:  # no threads in tests
        self._registry.recover_interrupted_jobs()

    def stop(self, timeout: float = 5.0) -> None:
        return None

    def submit(self, document_id: str, *, job_type=None):  # type: ignore[no-untyped-def]
        self.submitted.append(document_id)
        from engineering_rag.chatbot.states import JobType

        return self._registry.create_job(
            IngestionJobRecord(
                job_id=f"job-{len(self.submitted)}",
                document_id=document_id,
                job_type=job_type or JobType.INGEST,
            )
        )

    @property
    def is_running(self) -> bool:
        return True


class _FakeCollection:
    """In-memory stand-in for a Chroma collection, scoped by document_id.

    Delete-related tests reach the real ``rollback_document``/`` _build_bm25``
    codepaths through ``create_app``'s default orchestrator even though
    ingestion itself is stubbed out -- without an injected fake here, those
    calls would open the real ``engineering_documents_v1`` collection and
    rebuild the real BM25 index on disk.
    """

    def __init__(self) -> None:
        self.records: dict[str, str] = {}

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
    config = ChatbotConfig(storage=StorageConfig(root=tmp_path / "chatbot"))
    registry = Registry(config.storage.database_path)
    worker = _StubWorker(config, registry)

    from engineering_rag.chatbot.ingestion import IngestionOrchestrator

    fake_collection = _FakeCollection()
    isolated_orchestrator = IngestionOrchestrator(
        config=config,
        registry=registry,
        chroma_opener=lambda: fake_collection,
        bm25_builder=lambda: {"corpus_count": 0},
    )

    captured: dict[str, Any] = {}

    def fake_ask(query: str, *, retrieval_mode: str, metadata_filters: dict, top_k: int | None):
        captured["query"] = query
        captured["retrieval_mode"] = retrieval_mode
        captured["metadata_filters"] = metadata_filters

        class _Citation:
            citation_id = "S1"
            chunk_id = "c1"
            # Real citations carry the pipeline's document identity (the
            # source file's SHA-256), not this registry's own id -- mirror
            # that here so source-availability checks exercise the real
            # translation instead of accidentally matching by registry id.
            document_id = "ready-doc".ljust(64, "0")
            source_filename = "Report.pdf"
            page_numbers = [3]
            section_title = "Valves"
            supporting_quote = "Control valves regulate flow."
            content_hash = "h1"

        class _Validation:
            status = "PASS"
            checks_passed = ["no_unknown_citations", "has_inline_citation"]
            checks_failed: list[str] = []
            warnings: list[str] = []
            citation_coverage_ratio = 1.0
            repair_attempted = False

        class _Answer:
            status = "answered"
            answer = "Control valves regulate flow [S1]."
            citations = [_Citation()]
            validation = _Validation()
            stage_latencies_s = {"generation": 1.5}
            model_tag = "qwen3:4b"
            model_digest = "359d7dd4"
            total_latency_s = 1.6

        return (None, None, _Answer(), None, None)

    answering = GroundedAnsweringService(config=config, registry=registry, ask_runner=fake_ask)
    app = create_app(
        config,
        registry=registry,
        worker=worker,
        answering=answering,
        orchestrator=isolated_orchestrator,
    )

    with TestClient(app) as client:
        yield client, registry, worker, captured, config
    registry.close()


def _ready_document(registry: Registry, document_id: str = "ready-doc", **overrides) -> DocumentRecord:
    defaults = {
        "document_id": document_id,
        "stored_filename": "report.pdf",
        "display_name": "Report.pdf",
        "sha256": document_id.ljust(64, "0"),
        "media_type": "application/pdf",
        "byte_size": 1024,
        "parser_profile": "default",
        "status": DocumentStatus.READY,
        "total_chunks": 5,
    }
    defaults.update(overrides)
    return registry.create_document(DocumentRecord(**defaults))


class TestSystemEndpoints:
    def test_health_reports_the_version(self, env) -> None:
        client, *_ = env
        response = client.get(f"{API_PREFIX}/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_capabilities_advertises_only_pdf(self, env) -> None:
        client, *_ = env
        payload = client.get(f"{API_PREFIX}/capabilities").json()
        assert payload["accepted_extensions"] == [".pdf"]
        assert payload["accepted_media_types"] == ["application/pdf"]

    def test_capabilities_lists_all_four_retrieval_modes(self, env) -> None:
        client, *_ = env
        payload = client.get(f"{API_PREFIX}/capabilities").json()
        assert set(payload["retrieval_modes"]) == {
            "vector",
            "hybrid",
            "vector-rerank",
            "hybrid-rerank",
        }
        assert payload["default_retrieval_mode"] == "vector"

    def test_capabilities_exposes_parser_profiles_from_the_backend(self, env) -> None:
        client, *_ = env
        profiles = {p["id"] for p in client.get(f"{API_PREFIX}/capabilities").json()["parser_profiles"]}
        assert profiles == {"default", "high_fidelity", "scanned", "auto"}

    def test_capabilities_warns_that_generation_is_cpu_bound(self, env) -> None:
        client, *_ = env
        assert client.get(f"{API_PREFIX}/capabilities").json()["generation_is_cpu_bound"] is True

    def test_security_headers_are_present(self, env) -> None:
        client, *_ = env
        headers = client.get(f"{API_PREFIX}/health").headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert "X-Correlation-ID" in headers


class TestUpload:
    def test_valid_pdf_is_accepted_and_queued(self, env) -> None:
        client, registry, worker, _captured, _config = env
        response = client.post(
            f"{API_PREFIX}/documents",
            files={"file": ("report.pdf", MINIMAL_PDF, "application/pdf")},
            data={"parser_profile": "default"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["document"]["display_name"] == "report.pdf"
        assert body["job"] is not None
        assert worker.submitted == [body["document"]["document_id"]]

    def test_non_pdf_content_is_rejected_with_a_typed_error(self, env) -> None:
        client, *_ = env
        response = client.post(
            f"{API_PREFIX}/documents",
            files={"file": ("evil.pdf", b"MZ executable", "application/pdf")},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "UPLOAD_NOT_A_PDF"

    def test_unsupported_extension_is_rejected(self, env) -> None:
        client, *_ = env
        response = client.post(
            f"{API_PREFIX}/documents", files={"file": ("notes.txt", b"hello", "text/plain")}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "UPLOAD_UNSUPPORTED_EXTENSION"

    def test_unknown_parser_profile_is_rejected(self, env) -> None:
        client, *_ = env
        response = client.post(
            f"{API_PREFIX}/documents",
            files={"file": ("report.pdf", MINIMAL_PDF, "application/pdf")},
            data={"parser_profile": "not-a-profile"},
        )
        assert response.status_code == 422

    def test_duplicate_of_a_ready_document_returns_the_existing_one(self, env) -> None:
        client, registry, worker, _captured, _config = env
        first = client.post(
            f"{API_PREFIX}/documents", files={"file": ("a.pdf", MINIMAL_PDF, "application/pdf")}
        ).json()
        registry.update_document(first["document"]["document_id"], status=DocumentStatus.READY)

        second = client.post(
            f"{API_PREFIX}/documents", files={"file": ("same-content.pdf", MINIMAL_PDF, "application/pdf")}
        ).json()

        assert second["duplicate_of"] == first["document"]["document_id"]
        assert second["job"] is None
        assert len(worker.submitted) == 1, "a duplicate must not queue a second ingestion"

    def test_force_new_version_bypasses_duplicate_detection(self, env) -> None:
        client, registry, worker, _captured, _config = env
        first = client.post(
            f"{API_PREFIX}/documents", files={"file": ("a.pdf", MINIMAL_PDF, "application/pdf")}
        ).json()
        registry.update_document(first["document"]["document_id"], status=DocumentStatus.READY)

        second = client.post(
            f"{API_PREFIX}/documents",
            files={"file": ("a.pdf", MINIMAL_PDF, "application/pdf")},
            data={"force_new_version": "true"},
        ).json()

        assert second["duplicate_of"] is None
        assert len(worker.submitted) == 2

    def test_traversal_filename_does_not_escape_the_upload_directory(self, env) -> None:
        client, _registry, _worker, _captured, config = env
        client.post(
            f"{API_PREFIX}/documents",
            files={"file": ("../../../escape.pdf", MINIMAL_PDF, "application/pdf")},
        )
        stored = list(config.storage.uploads_dir.iterdir())
        assert len(stored) == 1
        assert stored[0].parent.resolve() == config.storage.uploads_dir.resolve()


class TestDocumentEndpoints:
    def test_listing_hides_deleted_documents(self, env) -> None:
        client, registry, *_ = env
        _ready_document(registry, "d1")
        _ready_document(registry, "d2")
        from engineering_rag.chatbot.models import utc_now

        registry.update_document("d2", deleted_at=utc_now(), status=DocumentStatus.DELETED)

        listed = client.get(f"{API_PREFIX}/documents").json()
        assert [d["document_id"] for d in listed] == ["d1"]

    def test_listing_can_filter_by_status(self, env) -> None:
        client, registry, *_ = env
        _ready_document(registry, "ready1")
        _ready_document(registry, "failed1", status=DocumentStatus.FAILED)

        listed = client.get(f"{API_PREFIX}/documents", params={"status": "READY"}).json()
        assert [d["document_id"] for d in listed] == ["ready1"]

    def test_detail_includes_job_history_and_validation(self, env) -> None:
        client, registry, *_ = env
        _ready_document(registry, "d1", validation_summary={"consistent": True}, warnings=["w1"])
        registry.create_job(IngestionJobRecord(job_id="j1", document_id="d1"))

        payload = client.get(f"{API_PREFIX}/documents/d1").json()
        assert payload["validation_summary"] == {"consistent": True}
        assert payload["warnings"] == ["w1"]
        assert [j["job_id"] for j in payload["jobs"]] == ["j1"]

    def test_missing_document_returns_a_typed_404(self, env) -> None:
        client, *_ = env
        response = client.get(f"{API_PREFIX}/documents/nope")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == ErrorCode.DOCUMENT_NOT_FOUND

    def test_delete_marks_the_document_deleted_and_unsearchable(self, env) -> None:
        client, registry, *_ = env
        _ready_document(registry, "d1")

        response = client.delete(f"{API_PREFIX}/documents/d1")
        assert response.status_code == 200
        assert response.json()["deleted"] is True
        assert registry.get_document("d1").status is DocumentStatus.DELETED

    def test_delete_uses_the_same_injected_orchestrator_as_the_worker(self, tmp_path: Path) -> None:
        """Regression test: delete_document must not fall back to a fresh,
        real-pipeline orchestrator -- it has to reuse whatever orchestrator
        (real or, as here, fake) the app was built with, exactly like the
        worker does. Otherwise an injected fake pipeline would apply to
        ingestion but silently not to deletion.
        """
        from engineering_rag.chatbot.ingestion import IngestionOrchestrator

        config = ChatbotConfig(storage=StorageConfig(root=tmp_path / "chatbot"))
        registry = Registry(config.storage.database_path)
        _ready_document(registry, "d1")

        orchestrator = IngestionOrchestrator(config=config, registry=registry)
        calls: list[str] = []
        orchestrator.rollback_document = lambda document_id: calls.append(document_id) or ["c1", "c2"]  # type: ignore[method-assign]
        orchestrator._build_bm25 = lambda: calls.append("bm25_rebuilt")  # type: ignore[method-assign]

        app = create_app(
            config,
            registry=registry,
            worker=_StubWorker(config, registry),
            orchestrator=orchestrator,
            start_worker=False,
        )
        with TestClient(app) as client:
            response = client.delete(f"{API_PREFIX}/documents/d1")
            assert response.status_code == 200
            assert response.json()["chunks_removed"] == 2
            # Delete must pass the pipeline's own document identity (source
            # SHA-256), not this registry's id -- that's what Chroma/BM25
            # actually key records by.
            assert calls == ["d1".ljust(64, "0"), "bm25_rebuilt"]
            assert client.get(f"{API_PREFIX}/documents/d1").status_code == 404


class TestDocumentSource:
    """The read-only PDF-serving route the citation viewer opens."""

    def test_serves_the_registered_pdf_with_the_correct_content_type(self, env, tmp_path: Path) -> None:
        client, registry, *_ = env
        pdf_path = tmp_path / "stored.pdf"
        pdf_path.write_bytes(MINIMAL_PDF)
        _ready_document(registry, "d1", source_path=str(pdf_path))

        response = client.get(f"{API_PREFIX}/documents/d1/source")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content == MINIMAL_PDF

    def test_range_requests_are_honored(self, env, tmp_path: Path) -> None:
        """PDF.js fetches pages via byte ranges; Starlette's FileResponse handles this
        natively, but the behavior is load-bearing for the viewer so it's pinned here."""
        client, registry, *_ = env
        content = b"0123456789" * 100
        pdf_path = tmp_path / "stored.pdf"
        pdf_path.write_bytes(content)
        _ready_document(registry, "d1", source_path=str(pdf_path))

        response = client.get(f"{API_PREFIX}/documents/d1/source", headers={"Range": "bytes=0-9"})
        assert response.status_code == 206
        assert response.headers["content-range"] == f"bytes 0-9/{len(content)}"
        assert response.content == content[:10]

    def test_unknown_document_id_is_a_safe_404_not_a_path_traversal(self, env) -> None:
        """document_id is looked up against the registry before any filesystem access, so a
        path-shaped id can never reach the filesystem. A multi-segment attempt (containing a
        literal or percent-encoded ``/``) never even matches the single-segment
        ``{document_id}`` route -- FastAPI/Starlette itself 404s it before any application
        code runs; a single-segment id that just doesn't exist gets our own typed 404."""
        client, *_ = env
        for attempt in ("../../etc/passwd", "..%2F..%2Fetc%2Fpasswd", "d1/../../secrets"):
            response = client.get(f"{API_PREFIX}/documents/{attempt}/source")
            assert response.status_code == 404
            assert "traceback" not in response.text.lower()
            assert str(Path.cwd()) not in response.text

        response = client.get(f"{API_PREFIX}/documents/nope/source")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == ErrorCode.DOCUMENT_NOT_FOUND

    def test_deleted_document_source_is_a_safe_404(self, env) -> None:
        client, registry, *_ = env
        from engineering_rag.chatbot.models import utc_now

        _ready_document(registry, "d1")
        registry.update_document("d1", deleted_at=utc_now(), status=DocumentStatus.DELETED)

        response = client.get(f"{API_PREFIX}/documents/d1/source")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == ErrorCode.DOCUMENT_NOT_FOUND

    def test_missing_source_file_on_disk_is_a_safe_404_not_a_crash(self, env, tmp_path: Path) -> None:
        client, registry, *_ = env
        _ready_document(registry, "d1", source_path=str(tmp_path / "never-written.pdf"))

        response = client.get(f"{API_PREFIX}/documents/d1/source")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == ErrorCode.DOCUMENT_NOT_FOUND
        assert str(tmp_path) not in response.text

    def test_document_with_no_source_path_is_a_safe_404(self, env) -> None:
        client, registry, *_ = env
        _ready_document(registry, "d1", source_path=None)

        response = client.get(f"{API_PREFIX}/documents/d1/source")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == ErrorCode.DOCUMENT_NOT_FOUND

    def test_unsafe_filename_characters_are_sanitized_in_content_disposition(
        self, env, tmp_path: Path
    ) -> None:
        """A malicious or accidental display_name (quotes, CRLF, path separators) must never
        reach the Content-Disposition header unsanitized -- header-injection defense."""
        client, registry, *_ = env
        pdf_path = tmp_path / "stored.pdf"
        pdf_path.write_bytes(MINIMAL_PDF)
        unsafe_name = 'evil".pdf\r\nX-Injected: yes\r\n\r\n../../etc/passwd'
        _ready_document(registry, "d1", source_path=str(pdf_path), display_name=unsafe_name)

        response = client.get(f"{API_PREFIX}/documents/d1/source")
        assert response.status_code == 200
        disposition = response.headers["content-disposition"]
        assert "\r" not in disposition
        assert "\n" not in disposition
        # The real security property: no second header was smuggled in via CRLF injection --
        # the sanitizer already stripped CR/LF, so "X-Injected"/".." surviving as harmless
        # literal text *inside* the one filename value is fine (it is only ever a suggested
        # download name; the byte content actually served always comes from the registry's
        # own source_path, never from this string). A genuinely injected header would show up
        # as its own entry in response.headers.
        assert "X-Injected" not in response.headers


class TestJobEndpoints:
    def test_job_status_is_returned(self, env) -> None:
        client, registry, *_ = env
        _ready_document(registry, "d1")
        registry.create_job(IngestionJobRecord(job_id="j1", document_id="d1"))

        payload = client.get(f"{API_PREFIX}/jobs/j1").json()
        assert payload["state"] == "QUEUED"
        assert payload["progress"] == 0.0

    def test_missing_job_returns_a_typed_404(self, env) -> None:
        client, *_ = env
        response = client.get(f"{API_PREFIX}/jobs/nope")
        assert response.json()["error"]["code"] == ErrorCode.JOB_NOT_FOUND

    def test_retrying_a_running_job_is_refused(self, env) -> None:
        client, registry, *_ = env
        _ready_document(registry, "d1")
        registry.create_job(IngestionJobRecord(job_id="j1", document_id="d1"))
        registry.update_job("j1", state=JobState.RUNNING)

        response = client.post(f"{API_PREFIX}/jobs/j1/retry")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == ErrorCode.INVALID_STATE_TRANSITION

    def test_a_failed_job_can_be_retried(self, env) -> None:
        client, registry, *_ = env
        _ready_document(registry, "d1")
        registry.create_job(IngestionJobRecord(job_id="j1", document_id="d1"))
        registry.update_job("j1", state=JobState.RUNNING)
        registry.update_job("j1", state=JobState.FAILED)

        assert client.post(f"{API_PREFIX}/jobs/j1/retry").status_code == 200

    def test_cancelling_a_finished_job_is_refused(self, env) -> None:
        client, registry, *_ = env
        _ready_document(registry, "d1")
        registry.create_job(IngestionJobRecord(job_id="j1", document_id="d1"))
        registry.update_job("j1", state=JobState.RUNNING)
        registry.update_job("j1", state=JobState.READY)

        assert client.post(f"{API_PREFIX}/jobs/j1/cancel").status_code == 409

    def test_sse_stream_replays_current_state_for_a_finished_job(self, env) -> None:
        """A late subscriber must not be stuck showing 'queued' forever."""
        client, registry, *_ = env
        _ready_document(registry, "d1")
        registry.create_job(IngestionJobRecord(job_id="j1", document_id="d1"))
        registry.update_job("j1", state=JobState.RUNNING)
        registry.update_job("j1", state=JobState.READY, progress=1.0)

        with client.stream("GET", f"{API_PREFIX}/jobs/j1/events") as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())
        assert '"type": "snapshot"' in body
        assert '"state": "READY"' in body


class TestConversations:
    def test_create_list_rename_delete(self, env) -> None:
        client, *_ = env
        created = client.post(f"{API_PREFIX}/conversations", json={"title": "Valves"}).json()
        cid = created["conversation_id"]

        assert [c["conversation_id"] for c in client.get(f"{API_PREFIX}/conversations").json()] == [cid]

        renamed = client.patch(f"{API_PREFIX}/conversations/{cid}", json={"title": "Renamed"}).json()
        assert renamed["title"] == "Renamed"

        assert client.delete(f"{API_PREFIX}/conversations/{cid}").status_code == 200
        assert client.get(f"{API_PREFIX}/conversations/{cid}").status_code == 404

    def test_invalid_retrieval_mode_is_rejected(self, env) -> None:
        client, *_ = env
        cid = client.post(f"{API_PREFIX}/conversations", json={}).json()["conversation_id"]
        response = client.patch(f"{API_PREFIX}/conversations/{cid}", json={"retrieval_mode": "telepathy"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == ErrorCode.INVALID_RETRIEVAL_MODE

    def test_missing_conversation_returns_a_typed_404(self, env) -> None:
        client, *_ = env
        assert (
            client.get(f"{API_PREFIX}/conversations/nope").json()["error"]["code"]
            == ErrorCode.CONVERSATION_NOT_FOUND
        )


class TestAskSelectionIsolation:
    """The selection boundary, enforced through the real HTTP layer."""

    def _conversation(self, client) -> str:
        return client.post(f"{API_PREFIX}/conversations", json={}).json()["conversation_id"]

    def test_answer_is_scoped_to_the_selected_documents(self, env) -> None:
        client, registry, _worker, captured, _config = env
        _ready_document(registry, "ready-doc")
        _ready_document(registry, "other-doc")
        cid = self._conversation(client)

        response = client.post(
            f"{API_PREFIX}/conversations/{cid}/messages",
            json={"query": "What is a valve?", "selected_document_ids": ["ready-doc"]},
        )
        assert response.status_code == 200
        # The filter reached the pipeline as a real query-time restriction,
        # translated to the pipeline's own document identity (source SHA-256).
        assert captured["metadata_filters"] == {"document_id": ["ready-doc".ljust(64, "0")]}
        assert "other-doc" not in str(captured["metadata_filters"])

    def test_multi_document_selection_passes_all_selected_ids(self, env) -> None:
        client, registry, _worker, captured, _config = env
        _ready_document(registry, "ready-doc")
        _ready_document(registry, "second-doc")
        cid = self._conversation(client)

        client.post(
            f"{API_PREFIX}/conversations/{cid}/messages",
            json={"query": "q", "selected_document_ids": ["ready-doc", "second-doc"]},
        )
        assert captured["metadata_filters"] == {
            "document_id": ["ready-doc".ljust(64, "0"), "second-doc".ljust(64, "0")]
        }

    def test_empty_selection_is_refused_not_widened(self, env) -> None:
        client, registry, _worker, captured, _config = env
        _ready_document(registry, "ready-doc")
        cid = self._conversation(client)

        response = client.post(
            f"{API_PREFIX}/conversations/{cid}/messages",
            json={"query": "q", "selected_document_ids": []},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == ErrorCode.EMPTY_DOCUMENT_SELECTION
        assert "metadata_filters" not in captured, "the pipeline must not run at all"

    def test_selecting_a_non_ready_document_is_refused(self, env) -> None:
        client, registry, *_ = env
        _ready_document(registry, "processing-doc", status=DocumentStatus.PROCESSING)
        cid = self._conversation(client)

        response = client.post(
            f"{API_PREFIX}/conversations/{cid}/messages",
            json={"query": "q", "selected_document_ids": ["processing-doc"]},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == ErrorCode.DOCUMENT_NOT_READY

    def test_selecting_a_deleted_document_is_refused(self, env) -> None:
        client, registry, *_ = env
        from engineering_rag.chatbot.models import utc_now

        _ready_document(registry, "gone")
        registry.update_document("gone", deleted_at=utc_now(), status=DocumentStatus.DELETED)
        cid = self._conversation(client)

        response = client.post(
            f"{API_PREFIX}/conversations/{cid}/messages",
            json={"query": "q", "selected_document_ids": ["gone"]},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == ErrorCode.UNKNOWN_DOCUMENT_SELECTED

    def test_mixed_valid_and_invalid_selection_fails_safely(self, env) -> None:
        """Answering the valid subset silently would hide a wrong mental model."""
        client, registry, _worker, captured, _config = env
        _ready_document(registry, "ready-doc")
        cid = self._conversation(client)

        response = client.post(
            f"{API_PREFIX}/conversations/{cid}/messages",
            json={"query": "q", "selected_document_ids": ["ready-doc", "missing-doc"]},
        )
        assert response.status_code == 404
        assert "metadata_filters" not in captured

    def test_a_rejected_question_leaves_no_orphan_message(self, env) -> None:
        client, registry, *_ = env
        cid = self._conversation(client)
        client.post(
            f"{API_PREFIX}/conversations/{cid}/messages",
            json={"query": "q", "selected_document_ids": []},
        )
        assert registry.list_messages(cid) == []

    def test_unknown_retrieval_mode_is_rejected(self, env) -> None:
        client, registry, *_ = env
        _ready_document(registry, "ready-doc")
        cid = self._conversation(client)

        response = client.post(
            f"{API_PREFIX}/conversations/{cid}/messages",
            json={"query": "q", "selected_document_ids": ["ready-doc"], "retrieval_mode": "psychic"},
        )
        # A typed, machine-readable rejection rather than a raw schema error,
        # so the UI can explain what went wrong.
        assert response.status_code == 400
        assert response.json()["error"]["code"] == ErrorCode.INVALID_RETRIEVAL_MODE

    @pytest.mark.parametrize("mode", ["vector", "hybrid", "vector-rerank", "hybrid-rerank"])
    def test_every_retrieval_mode_reaches_the_pipeline(self, env, mode: str) -> None:
        client, registry, _worker, captured, _config = env
        _ready_document(registry, "ready-doc")
        cid = self._conversation(client)

        client.post(
            f"{API_PREFIX}/conversations/{cid}/messages",
            json={"query": "q", "selected_document_ids": ["ready-doc"], "retrieval_mode": mode},
        )
        assert captured["retrieval_mode"] == mode


class TestAnswerPersistence:
    def test_both_messages_are_persisted_with_citations(self, env) -> None:
        client, registry, *_ = env
        _ready_document(registry, "ready-doc")
        cid = client.post(f"{API_PREFIX}/conversations", json={}).json()["conversation_id"]

        messages = client.post(
            f"{API_PREFIX}/conversations/{cid}/messages",
            json={"query": "What is a valve?", "selected_document_ids": ["ready-doc"]},
        ).json()

        assert [m["role"] for m in messages] == ["user", "assistant"]
        assistant = messages[1]
        assert assistant["status"] == "answered"
        assert assistant["citations"][0]["citation_id"] == "S1"
        assert assistant["citations"][0]["page_numbers"] == [3]
        assert assistant["model_tag"] == "qwen3:4b"
        assert assistant["grounding"]["status"] == "PASS"

    def test_citations_survive_deleting_their_source_but_are_marked_unavailable(self, env) -> None:
        """History stays honest: the citation is never rewritten, only flagged."""
        client, registry, *_ = env
        from engineering_rag.chatbot.models import utc_now

        _ready_document(registry, "ready-doc")
        cid = client.post(f"{API_PREFIX}/conversations", json={}).json()["conversation_id"]
        client.post(
            f"{API_PREFIX}/conversations/{cid}/messages",
            json={"query": "q", "selected_document_ids": ["ready-doc"]},
        )

        before = client.get(f"{API_PREFIX}/conversations/{cid}").json()
        assert before["messages"][1]["citations"][0]["source_available"] is True

        registry.update_document("ready-doc", deleted_at=utc_now(), status=DocumentStatus.DELETED)
        detail = client.get(f"{API_PREFIX}/conversations/{cid}").json()

        citation = detail["messages"][1]["citations"][0]
        assert citation["citation_id"] == "S1", "the historical citation must not be rewritten"
        assert citation["source_available"] is False

    def test_a_generation_failure_is_reported_without_prose(self, env, tmp_path: Path) -> None:
        """Unvalidated model text must never be presented as an answer."""
        config = ChatbotConfig(storage=StorageConfig(root=tmp_path / "fail"))
        registry = Registry(config.storage.database_path)
        _ready_document(registry, "ready-doc")

        def exploding_ask(*args, **kwargs):
            raise RuntimeError("model unreachable")

        answering = GroundedAnsweringService(config=config, registry=registry, ask_runner=exploding_ask)
        app = create_app(
            config,
            registry=registry,
            worker=_StubWorker(config, registry),
            answering=answering,
            start_worker=False,
        )
        with TestClient(app) as client:
            cid = client.post(f"{API_PREFIX}/conversations", json={}).json()["conversation_id"]
            messages = client.post(
                f"{API_PREFIX}/conversations/{cid}/messages",
                json={"query": "q", "selected_document_ids": ["ready-doc"]},
            ).json()

        assistant = messages[1]
        assert assistant["status"] == "failed"
        assert assistant["content"] == ""
        assert assistant["error_code"] is not None
        registry.close()


class TestAnswerOutcomeMapping:
    def test_refusal_is_not_treated_as_an_error(self) -> None:
        outcome = AnswerOutcome(status="insufficient_evidence", answer="No evidence found.")
        assert outcome.error_code is None

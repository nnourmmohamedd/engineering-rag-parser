"""Durable registry: persistence, schema versioning, transitions and restart recovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_rag.chatbot.models import (
    REGISTRY_SCHEMA_VERSION,
    ConversationMessageRecord,
    ConversationRecord,
    DocumentRecord,
    IngestionJobRecord,
    StageTiming,
)
from engineering_rag.chatbot.states import (
    DocumentStatus,
    InvalidStateTransitionError,
    JobStage,
    JobState,
)
from engineering_rag.chatbot.storage import Registry, RegistrySchemaError, new_id


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    reg = Registry(tmp_path / "registry.sqlite3")
    yield reg
    reg.close()


def _document(**overrides) -> DocumentRecord:
    defaults = {
        "document_id": new_id(),
        "stored_filename": "report.pdf",
        "display_name": "Report.pdf",
        "sha256": "a" * 64,
        "media_type": "application/pdf",
        "byte_size": 1024,
        "parser_profile": "default",
    }
    defaults.update(overrides)
    return DocumentRecord(**defaults)


def _job(document_id: str, **overrides) -> IngestionJobRecord:
    defaults = {"job_id": new_id(), "document_id": document_id}
    defaults.update(overrides)
    return IngestionJobRecord(**defaults)


class TestSchemaVersioning:
    def test_fresh_database_records_its_schema_version(self, tmp_path: Path) -> None:
        reg = Registry(tmp_path / "r.sqlite3")
        row = reg._conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
        reg.close()
        assert int(row["value"]) == REGISTRY_SCHEMA_VERSION

    def test_reopening_an_existing_database_is_idempotent(self, tmp_path: Path) -> None:
        path = tmp_path / "r.sqlite3"
        first = Registry(path)
        first.create_document(_document(document_id="d1"))
        first.close()

        second = Registry(path)
        assert second.get_document("d1") is not None
        second.close()

    def test_refuses_a_database_from_a_newer_build(self, tmp_path: Path) -> None:
        """Misreading columns silently is far worse than refusing to start."""
        path = tmp_path / "r.sqlite3"
        reg = Registry(path)
        reg._conn.execute(
            "UPDATE schema_meta SET value = ? WHERE key='schema_version'",
            (str(REGISTRY_SCHEMA_VERSION + 1),),
        )
        reg._conn.commit()
        reg.close()

        with pytest.raises(RegistrySchemaError, match="written by schema version"):
            Registry(path)


class TestDocumentPersistence:
    def test_create_and_read_round_trips_every_field(self, registry: Registry) -> None:
        record = _document(
            page_count=12,
            warnings=["ocr low confidence"],
            validation_summary={"status": "PASS_WITH_WARNINGS"},
        )
        registry.create_document(record)

        loaded = registry.get_document(record.document_id)
        assert loaded is not None
        assert loaded.warnings == ["ocr low confidence"]
        assert loaded.validation_summary == {"status": "PASS_WITH_WARNINGS"}
        assert loaded.page_count == 12
        assert loaded.status is DocumentStatus.UPLOADED

    def test_update_patches_only_named_columns(self, registry: Registry) -> None:
        record = registry.create_document(_document(display_name="Original.pdf"))
        updated = registry.update_document(record.document_id, status=DocumentStatus.READY, total_chunks=42)
        assert updated.status is DocumentStatus.READY
        assert updated.total_chunks == 42
        assert updated.display_name == "Original.pdf"

    def test_update_bumps_updated_at(self, registry: Registry) -> None:
        record = registry.create_document(_document())
        updated = registry.update_document(record.document_id, total_chunks=1)
        assert updated.updated_at >= record.updated_at

    def test_unknown_field_is_rejected_rather_than_ignored(self, registry: Registry) -> None:
        record = registry.create_document(_document())
        with pytest.raises(ValueError, match="unknown document field"):
            registry.update_document(record.document_id, not_a_column="x")

    def test_updating_a_missing_document_raises(self, registry: Registry) -> None:
        with pytest.raises(KeyError):
            registry.update_document("does-not-exist", total_chunks=1)

    def test_soft_deleted_documents_are_hidden_by_default(self, registry: Registry) -> None:
        from engineering_rag.chatbot.models import utc_now

        record = registry.create_document(_document())
        registry.update_document(record.document_id, deleted_at=utc_now(), status=DocumentStatus.DELETED)

        assert registry.list_documents() == []
        assert len(registry.list_documents(include_deleted=True)) == 1
        assert registry.get_document(record.document_id).is_deleted is True

    def test_find_by_sha256_supports_duplicate_detection(self, registry: Registry) -> None:
        registry.create_document(_document(document_id="d1", sha256="b" * 64))
        registry.create_document(_document(document_id="d2", sha256="c" * 64))
        found = registry.find_documents_by_sha256("b" * 64)
        assert [d.document_id for d in found] == ["d1"]


class TestJobPersistence:
    def test_create_and_read_round_trips_stage_timings(self, registry: Registry) -> None:
        doc = registry.create_document(_document())
        job = _job(doc.document_id, stage_timings=[StageTiming(stage=JobStage.PARSING, duration_s=1.5)])
        registry.create_job(job)

        loaded = registry.get_job(job.job_id)
        assert loaded is not None
        assert loaded.stage_timings[0].stage is JobStage.PARSING
        assert loaded.stage_timings[0].duration_s == 1.5

    def test_state_change_is_validated_against_the_transition_table(self, registry: Registry) -> None:
        doc = registry.create_document(_document())
        job = registry.create_job(_job(doc.document_id))
        with pytest.raises(InvalidStateTransitionError):
            registry.update_job(job.job_id, state=JobState.READY)  # QUEUED -> READY is illegal

    def test_legal_state_change_is_persisted(self, registry: Registry) -> None:
        doc = registry.create_document(_document())
        job = registry.create_job(_job(doc.document_id))
        running = registry.update_job(job.job_id, state=JobState.RUNNING, stage=JobStage.PARSING)
        assert running.state is JobState.RUNNING
        assert running.stage is JobStage.PARSING
        assert registry.update_job(job.job_id, state=JobState.READY).state is JobState.READY

    def test_error_evidence_is_preserved_on_failure(self, registry: Registry) -> None:
        doc = registry.create_document(_document())
        job = registry.create_job(_job(doc.document_id))
        registry.update_job(job.job_id, state=JobState.RUNNING)
        failed = registry.update_job(
            job.job_id,
            state=JobState.FAILED,
            stage=JobStage.PARSER_VALIDATION,
            error_code="PARSER_VALIDATION_FAILED",
            error_message="Parser validation gate did not pass.",
            retryable=True,
        )
        assert failed.error_code == "PARSER_VALIDATION_FAILED"
        assert failed.retryable is True
        # The stage that failed is retained, which is what retry and the UI need.
        assert failed.stage is JobStage.PARSER_VALIDATION

    def test_listing_filters_by_document_and_state(self, registry: Registry) -> None:
        doc_a = registry.create_document(_document(document_id="a"))
        doc_b = registry.create_document(_document(document_id="b", sha256="d" * 64))
        registry.create_job(_job(doc_a.document_id, job_id="j1"))
        registry.create_job(_job(doc_b.document_id, job_id="j2"))

        assert [j.job_id for j in registry.list_jobs(document_id="a")] == ["j1"]
        assert {j.job_id for j in registry.list_jobs(states=[JobState.QUEUED])} == {"j1", "j2"}

    def test_latest_job_for_document_returns_the_most_recent(self, registry: Registry) -> None:
        doc = registry.create_document(_document())
        registry.create_job(_job(doc.document_id, job_id="old"))
        registry.create_job(_job(doc.document_id, job_id="new", attempt=2))
        assert registry.latest_job_for_document(doc.document_id).job_id == "new"


class TestRestartRecovery:
    """A crash mid-ingestion must never leave a searchable, half-indexed document."""

    def test_active_jobs_become_interrupted_and_retryable(self, tmp_path: Path) -> None:
        path = tmp_path / "r.sqlite3"
        first = Registry(path)
        doc = first.create_document(_document(document_id="d1", status=DocumentStatus.PROCESSING))
        first.create_job(_job(doc.document_id, job_id="j1"))
        first.update_job("j1", state=JobState.RUNNING, stage=JobStage.EMBEDDING)
        first.close()  # simulates the process dying mid-embedding

        second = Registry(path)
        recovered = second.recover_interrupted_jobs()

        assert [j.job_id for j in recovered] == ["j1"]
        job = second.get_job("j1")
        assert job.state is JobState.INTERRUPTED
        assert job.retryable is True
        assert job.error_code == "INGESTION_INTERRUPTED"
        second.close()

    def test_document_leaves_processing_and_is_not_searchable(self, tmp_path: Path) -> None:
        path = tmp_path / "r.sqlite3"
        first = Registry(path)
        first.create_document(_document(document_id="d1", status=DocumentStatus.PROCESSING))
        first.create_job(_job("d1", job_id="j1"))
        first.update_job("j1", state=JobState.RUNNING, stage=JobStage.VECTOR_INDEXING)
        first.close()

        second = Registry(path)
        second.recover_interrupted_jobs()
        document = second.get_document("d1")

        from engineering_rag.chatbot.states import is_retrievable

        assert document.status is DocumentStatus.INTERRUPTED
        assert is_retrievable(document.status) is False
        second.close()

    def test_recovery_never_promotes_a_document_to_ready(self, tmp_path: Path) -> None:
        """The whole point: a half-finished run must not look successful."""
        path = tmp_path / "r.sqlite3"
        first = Registry(path)
        first.create_document(_document(document_id="d1", status=DocumentStatus.PROCESSING))
        first.create_job(_job("d1", job_id="j1"))
        first.update_job("j1", state=JobState.RUNNING, stage=JobStage.INDEX_VALIDATION)
        first.close()

        second = Registry(path)
        second.recover_interrupted_jobs()
        assert second.get_document("d1").status is not DocumentStatus.READY
        second.close()

    def test_already_ready_documents_are_untouched_by_recovery(self, tmp_path: Path) -> None:
        path = tmp_path / "r.sqlite3"
        first = Registry(path)
        first.create_document(_document(document_id="done", status=DocumentStatus.READY))
        first.create_job(_job("done", job_id="j-done"))
        first.update_job("j-done", state=JobState.RUNNING)
        first.update_job("j-done", state=JobState.READY)
        first.close()

        second = Registry(path)
        recovered = second.recover_interrupted_jobs()
        assert recovered == []
        assert second.get_document("done").status is DocumentStatus.READY
        second.close()

    def test_recovery_is_idempotent(self, tmp_path: Path) -> None:
        path = tmp_path / "r.sqlite3"
        first = Registry(path)
        first.create_document(_document(document_id="d1", status=DocumentStatus.PROCESSING))
        first.create_job(_job("d1", job_id="j1"))
        first.update_job("j1", state=JobState.RUNNING)
        first.close()

        second = Registry(path)
        assert len(second.recover_interrupted_jobs()) == 1
        assert second.recover_interrupted_jobs() == []
        second.close()


class TestConversationPersistence:
    def test_conversation_round_trips_selection_and_mode(self, registry: Registry) -> None:
        convo = ConversationRecord(
            conversation_id=new_id(),
            title="Valve sizing",
            selected_document_ids=["d1", "d2"],
            retrieval_mode="hybrid",
        )
        registry.create_conversation(convo)

        loaded = registry.get_conversation(convo.conversation_id)
        assert loaded.selected_document_ids == ["d1", "d2"]
        assert loaded.retrieval_mode == "hybrid"

    def test_messages_are_ordered_and_scoped_to_their_conversation(self, registry: Registry) -> None:
        convo = registry.create_conversation(ConversationRecord(conversation_id="c1", title="T"))
        other = registry.create_conversation(ConversationRecord(conversation_id="c2", title="Other"))
        registry.add_message(
            ConversationMessageRecord(
                message_id="m1", conversation_id=convo.conversation_id, role="user", content="q"
            )
        )
        registry.add_message(
            ConversationMessageRecord(
                message_id="m2", conversation_id=convo.conversation_id, role="assistant", content="a"
            )
        )
        registry.add_message(
            ConversationMessageRecord(
                message_id="m3", conversation_id=other.conversation_id, role="user", content="x"
            )
        )

        assert [m.message_id for m in registry.list_messages("c1")] == ["m1", "m2"]
        assert [m.message_id for m in registry.list_messages("c2")] == ["m3"]

    def test_citations_are_stored_immutably_with_the_message(self, registry: Registry) -> None:
        """Deleting a document later must not retroactively rewrite what was cited."""
        registry.create_conversation(ConversationRecord(conversation_id="c1", title="T"))
        citations = [{"citation_id": "S1", "document_id": "d1", "page_numbers": [3]}]
        registry.add_message(
            ConversationMessageRecord(
                message_id="m1",
                conversation_id="c1",
                role="assistant",
                content="Answer [S1].",
                citations=citations,
                status="answered",
            )
        )
        loaded = registry.get_message("m1")
        assert loaded.citations == citations
        assert loaded.status == "answered"

    def test_adding_a_message_touches_the_conversation(self, registry: Registry) -> None:
        convo = registry.create_conversation(ConversationRecord(conversation_id="c1", title="T"))
        registry.add_message(
            ConversationMessageRecord(message_id="m1", conversation_id="c1", role="user", content="q")
        )
        assert registry.get_conversation("c1").updated_at >= convo.updated_at

    def test_deleting_a_conversation_removes_its_messages(self, registry: Registry) -> None:
        registry.create_conversation(ConversationRecord(conversation_id="c1", title="T"))
        registry.add_message(
            ConversationMessageRecord(message_id="m1", conversation_id="c1", role="user", content="q")
        )
        registry.delete_conversation("c1")

        assert registry.get_conversation("c1") is None
        assert registry.list_messages("c1") == []

    def test_renaming_a_conversation_persists(self, registry: Registry) -> None:
        registry.create_conversation(ConversationRecord(conversation_id="c1", title="Old"))
        assert registry.update_conversation("c1", title="New").title == "New"

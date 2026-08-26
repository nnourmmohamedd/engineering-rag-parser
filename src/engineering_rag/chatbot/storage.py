"""Durable SQLite registry for documents, ingestion jobs and conversations.

Uses the standard library's ``sqlite3`` directly rather than an ORM: this is
a single-user local registry with a handful of tables, and an explicit schema
plus a version check is both smaller and easier to audit than an ORM's
migration machinery would be here (see ``docs/chatbot/ARCHITECTURE.md``).

Two behaviours matter more than anything else in this module:

**Schema versioning.** :data:`~.models.REGISTRY_SCHEMA_VERSION` is stored in
the database. Opening a database written by a *newer* version raises rather
than silently misreading columns.

**Restart recovery.** :meth:`Registry.recover_interrupted_jobs` runs at
startup and reclassifies every job left in an active state by a crash. Those
jobs become ``INTERRUPTED`` and their documents leave ``PROCESSING`` -- a
half-indexed document must never appear ``READY`` just because the process
died at the wrong moment. Evidence is preserved so an explicit retry can
report what happened.

Concurrency: SQLite is opened per-connection with WAL enabled and a busy
timeout. Every write goes through :meth:`Registry._write`, which wraps the
statement in a transaction, so a failed write never leaves a partial row.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import (
    REGISTRY_SCHEMA_VERSION,
    ConversationMessageRecord,
    ConversationRecord,
    DocumentRecord,
    IngestionJobRecord,
    StageTiming,
    utc_now,
)
from .states import (
    ACTIVE_JOB_STATES,
    DocumentStatus,
    JobStage,
    JobState,
    JobType,
    assert_transition,
)

__all__ = ["Registry", "RegistrySchemaError", "new_id"]


class RegistrySchemaError(RuntimeError):
    """Raised when the on-disk database schema is not one this build understands."""


def new_id() -> str:
    """A short, collision-safe identifier for a document/job/conversation."""
    return uuid.uuid4().hex


_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    document_id        TEXT PRIMARY KEY,
    stored_filename    TEXT NOT NULL,
    display_name       TEXT NOT NULL,
    sha256             TEXT NOT NULL,
    media_type         TEXT NOT NULL,
    byte_size          INTEGER NOT NULL,
    page_count         INTEGER,
    parser_profile     TEXT NOT NULL,
    status             TEXT NOT NULL,
    version            INTEGER NOT NULL DEFAULT 1,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    source_path        TEXT,
    parser_run_id      TEXT,
    chunk_run_id       TEXT,
    index_version      TEXT,
    total_chunks       INTEGER,
    warnings           TEXT NOT NULL DEFAULT '[]',
    validation_summary TEXT NOT NULL DEFAULT '{}',
    deleted_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_documents_sha ON documents (sha256);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents (status);

CREATE TABLE IF NOT EXISTS jobs (
    job_id           TEXT PRIMARY KEY,
    document_id      TEXT NOT NULL,
    job_type         TEXT NOT NULL,
    state            TEXT NOT NULL,
    stage            TEXT NOT NULL,
    progress         REAL NOT NULL DEFAULT 0.0,
    attempt          INTEGER NOT NULL DEFAULT 1,
    started_at       TEXT,
    finished_at      TEXT,
    stage_timings    TEXT NOT NULL DEFAULT '[]',
    error_code       TEXT,
    error_message    TEXT,
    retryable        INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    correlation_id   TEXT,
    FOREIGN KEY (document_id) REFERENCES documents (document_id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_document ON jobs (document_id);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs (state);

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id       TEXT PRIMARY KEY,
    title                 TEXT NOT NULL,
    selected_document_ids TEXT NOT NULL DEFAULT '[]',
    retrieval_mode        TEXT NOT NULL DEFAULT 'vector',
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    message_id            TEXT PRIMARY KEY,
    conversation_id       TEXT NOT NULL,
    role                  TEXT NOT NULL,
    content               TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    status                TEXT,
    retrieval_mode        TEXT,
    selected_document_ids TEXT NOT NULL DEFAULT '[]',
    citations             TEXT NOT NULL DEFAULT '[]',
    stage_timings         TEXT NOT NULL DEFAULT '{}',
    grounding             TEXT NOT NULL DEFAULT '{}',
    model_tag             TEXT,
    model_digest          TEXT,
    provider              TEXT,
    error_code            TEXT,
    FOREIGN KEY (conversation_id) REFERENCES conversations (conversation_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages (conversation_id, created_at);
"""


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _dts(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class Registry:
    """Durable store for documents, ingestion jobs and conversations."""

    def __init__(self, db_path: Path | str) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # `check_same_thread=False` + an explicit lock: the API and the worker
        # thread share one registry, and SQLite's own thread check would
        # reject that even though every access here is serialized.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=30000")
        try:
            self._initialise()
        except Exception:
            # Never leak the handle when construction fails (e.g. a database
            # from a newer build): the caller has no object to close.
            self._conn.close()
            raise

    # --- lifecycle -------------------------------------------------------

    def _initialise(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            row = self._conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?)",
                    (str(REGISTRY_SCHEMA_VERSION),),
                )
                self._conn.commit()
                return
            found = int(row["value"])
            if found > REGISTRY_SCHEMA_VERSION:
                raise RegistrySchemaError(
                    f"registry at {self._path.name} was written by schema version {found}, but this "
                    f"build understands at most {REGISTRY_SCHEMA_VERSION}. Upgrade the application "
                    "rather than letting it misread the database."
                )
            # Older versions would be migrated here; version 1 is the floor.

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """One atomic write transaction. Rolls back on any exception."""
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # --- documents -------------------------------------------------------

    def create_document(self, record: DocumentRecord) -> DocumentRecord:
        with self._write() as conn:
            conn.execute(
                """INSERT INTO documents (document_id, stored_filename, display_name, sha256,
                       media_type, byte_size, page_count, parser_profile, status, version,
                       created_at, updated_at, source_path, parser_run_id, chunk_run_id,
                       index_version, total_chunks, warnings, validation_summary, deleted_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.document_id,
                    record.stored_filename,
                    record.display_name,
                    record.sha256,
                    record.media_type,
                    record.byte_size,
                    record.page_count,
                    record.parser_profile,
                    record.status.value,
                    record.version,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                    record.source_path,
                    record.parser_run_id,
                    record.chunk_run_id,
                    record.index_version,
                    record.total_chunks,
                    json.dumps(record.warnings),
                    json.dumps(record.validation_summary),
                    _dts(record.deleted_at),
                ),
            )
        return record

    def get_document(self, document_id: str) -> DocumentRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM documents WHERE document_id = ?", (document_id,)
            ).fetchone()
        return self._row_to_document(row) if row else None

    def list_documents(self, *, include_deleted: bool = False) -> list[DocumentRecord]:
        sql = "SELECT * FROM documents"
        if not include_deleted:
            sql += " WHERE deleted_at IS NULL"
        sql += " ORDER BY created_at DESC"
        with self._lock:
            rows = self._conn.execute(sql).fetchall()
        return [self._row_to_document(r) for r in rows]

    def find_documents_by_sha256(self, sha256: str, *, include_deleted: bool = False) -> list[DocumentRecord]:
        sql = "SELECT * FROM documents WHERE sha256 = ?"
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        sql += " ORDER BY created_at DESC"
        with self._lock:
            rows = self._conn.execute(sql, (sha256,)).fetchall()
        return [self._row_to_document(r) for r in rows]

    def update_document(self, document_id: str, **fields: Any) -> DocumentRecord:
        """Patch selected columns. Unknown column names raise rather than being ignored."""
        if not fields:
            existing = self.get_document(document_id)
            if existing is None:
                raise KeyError(document_id)
            return existing

        allowed = {
            "stored_filename",
            "display_name",
            "sha256",
            "media_type",
            "byte_size",
            "page_count",
            "parser_profile",
            "status",
            "version",
            "source_path",
            "parser_run_id",
            "chunk_run_id",
            "index_version",
            "total_chunks",
            "warnings",
            "validation_summary",
            "deleted_at",
        }
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ValueError(f"unknown document field(s): {unknown}")

        assignments: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            assignments.append(f"{key} = ?")
            values.append(self._encode_document_value(key, value))
        assignments.append("updated_at = ?")
        values.append(utc_now().isoformat())
        values.append(document_id)

        with self._write() as conn:
            cursor = conn.execute(
                f"UPDATE documents SET {', '.join(assignments)} WHERE document_id = ?", values
            )
            if cursor.rowcount == 0:
                raise KeyError(document_id)
        updated = self.get_document(document_id)
        assert updated is not None
        return updated

    @staticmethod
    def _encode_document_value(key: str, value: Any) -> Any:
        if key in {"warnings", "validation_summary"}:
            return json.dumps(value)
        if key == "status":
            return value.value if isinstance(value, DocumentStatus) else value
        if key == "deleted_at":
            return _dts(value) if isinstance(value, datetime) else value
        return value

    @staticmethod
    def _row_to_document(row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            document_id=row["document_id"],
            stored_filename=row["stored_filename"],
            display_name=row["display_name"],
            sha256=row["sha256"],
            media_type=row["media_type"],
            byte_size=row["byte_size"],
            page_count=row["page_count"],
            parser_profile=row["parser_profile"],
            status=DocumentStatus(row["status"]),
            version=row["version"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            source_path=row["source_path"],
            parser_run_id=row["parser_run_id"],
            chunk_run_id=row["chunk_run_id"],
            index_version=row["index_version"],
            total_chunks=row["total_chunks"],
            warnings=json.loads(row["warnings"]),
            validation_summary=json.loads(row["validation_summary"]),
            deleted_at=_dt(row["deleted_at"]),
        )

    # --- jobs ------------------------------------------------------------

    def create_job(self, record: IngestionJobRecord) -> IngestionJobRecord:
        with self._write() as conn:
            conn.execute(
                """INSERT INTO jobs (job_id, document_id, job_type, state, stage, progress, attempt,
                       started_at, finished_at, stage_timings, error_code, error_message,
                       retryable, cancel_requested, correlation_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.job_id,
                    record.document_id,
                    record.job_type.value,
                    record.state.value,
                    record.stage.value,
                    record.progress,
                    record.attempt,
                    _dts(record.started_at),
                    _dts(record.finished_at),
                    json.dumps([t.model_dump(mode="json") for t in record.stage_timings]),
                    record.error_code,
                    record.error_message,
                    int(record.retryable),
                    int(record.cancel_requested),
                    record.correlation_id,
                ),
            )
        return record

    def get_job(self, job_id: str) -> IngestionJobRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(
        self, *, document_id: str | None = None, states: Sequence[JobState] | None = None
    ) -> list[IngestionJobRecord]:
        sql = "SELECT * FROM jobs"
        clauses: list[str] = []
        values: list[Any] = []
        if document_id is not None:
            clauses.append("document_id = ?")
            values.append(document_id)
        if states:
            placeholders = ",".join("?" for _ in states)
            clauses.append(f"state IN ({placeholders})")
            values.extend(s.value for s in states)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY rowid DESC"
        with self._lock:
            rows = self._conn.execute(sql, values).fetchall()
        return [self._row_to_job(r) for r in rows]

    def latest_job_for_document(self, document_id: str) -> IngestionJobRecord | None:
        jobs = self.list_jobs(document_id=document_id)
        return jobs[0] if jobs else None

    def update_job(self, job_id: str, **fields: Any) -> IngestionJobRecord:
        """Patch a job. A ``state`` change is validated against the transition table first."""
        current = self.get_job(job_id)
        if current is None:
            raise KeyError(job_id)

        if "state" in fields:
            target = fields["state"]
            target_state = JobState(target) if not isinstance(target, JobState) else target
            assert_transition(current.state, target_state)

        allowed = {
            "state",
            "stage",
            "progress",
            "attempt",
            "started_at",
            "finished_at",
            "stage_timings",
            "error_code",
            "error_message",
            "retryable",
            "cancel_requested",
            "correlation_id",
        }
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ValueError(f"unknown job field(s): {unknown}")

        assignments: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            assignments.append(f"{key} = ?")
            values.append(self._encode_job_value(key, value))
        values.append(job_id)

        with self._write() as conn:
            conn.execute(f"UPDATE jobs SET {', '.join(assignments)} WHERE job_id = ?", values)
        updated = self.get_job(job_id)
        assert updated is not None
        return updated

    @staticmethod
    def _encode_job_value(key: str, value: Any) -> Any:
        if key == "stage_timings":
            return json.dumps([t.model_dump(mode="json") if isinstance(t, StageTiming) else t for t in value])
        if key in {"state", "stage", "job_type"}:
            return value.value if hasattr(value, "value") else value
        if key in {"retryable", "cancel_requested"}:
            return int(bool(value))
        if key in {"started_at", "finished_at"}:
            return _dts(value) if isinstance(value, datetime) else value
        return value

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> IngestionJobRecord:
        return IngestionJobRecord(
            job_id=row["job_id"],
            document_id=row["document_id"],
            job_type=JobType(row["job_type"]),
            state=JobState(row["state"]),
            stage=JobStage(row["stage"]),
            progress=row["progress"],
            attempt=row["attempt"],
            started_at=_dt(row["started_at"]),
            finished_at=_dt(row["finished_at"]),
            stage_timings=[StageTiming(**t) for t in json.loads(row["stage_timings"])],
            error_code=row["error_code"],
            error_message=row["error_message"],
            retryable=bool(row["retryable"]),
            cancel_requested=bool(row["cancel_requested"]),
            correlation_id=row["correlation_id"],
        )

    # --- startup recovery -------------------------------------------------

    def recover_interrupted_jobs(self) -> list[IngestionJobRecord]:
        """Reclassify jobs left mid-flight by a crash/restart. Called once at startup.

        A job that was QUEUED or RUNNING when the process died cannot be
        trusted to have finished any stage cleanly, so it becomes
        ``INTERRUPTED`` (retryable) and its document is moved out of
        ``PROCESSING``. Crucially, a document is never promoted to ``READY``
        by recovery -- only a completed activation does that, so a
        half-indexed document stays unsearchable until an explicit retry.
        """
        recovered: list[IngestionJobRecord] = []
        for job in self.list_jobs(states=sorted(ACTIVE_JOB_STATES, key=lambda s: s.value)):
            updated = self.update_job(
                job.job_id,
                state=JobState.INTERRUPTED,
                finished_at=utc_now(),
                retryable=True,
                error_code="INGESTION_INTERRUPTED",
                error_message=(
                    "Processing was interrupted before it finished (the application stopped "
                    "mid-run). The document was not indexed; retry to process it again."
                ),
            )
            recovered.append(updated)

            document = self.get_document(job.document_id)
            if document is not None and document.status not in {
                DocumentStatus.READY,
                DocumentStatus.DELETED,
            }:
                self.update_document(job.document_id, status=DocumentStatus.INTERRUPTED)
        return recovered

    # --- conversations ----------------------------------------------------

    def create_conversation(self, record: ConversationRecord) -> ConversationRecord:
        with self._write() as conn:
            conn.execute(
                """INSERT INTO conversations (conversation_id, title, selected_document_ids,
                       retrieval_mode, created_at, updated_at) VALUES (?,?,?,?,?,?)""",
                (
                    record.conversation_id,
                    record.title,
                    json.dumps(record.selected_document_ids),
                    record.retrieval_mode,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                ),
            )
        return record

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM conversations WHERE conversation_id = ?", (conversation_id,)
            ).fetchone()
        return self._row_to_conversation(row) if row else None

    def list_conversations(self) -> list[ConversationRecord]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM conversations ORDER BY updated_at DESC").fetchall()
        return [self._row_to_conversation(r) for r in rows]

    def update_conversation(self, conversation_id: str, **fields: Any) -> ConversationRecord:
        allowed = {"title", "selected_document_ids", "retrieval_mode"}
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ValueError(f"unknown conversation field(s): {unknown}")

        assignments: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            assignments.append(f"{key} = ?")
            values.append(json.dumps(value) if key == "selected_document_ids" else value)
        assignments.append("updated_at = ?")
        values.append(utc_now().isoformat())
        values.append(conversation_id)

        with self._write() as conn:
            cursor = conn.execute(
                f"UPDATE conversations SET {', '.join(assignments)} WHERE conversation_id = ?", values
            )
            if cursor.rowcount == 0:
                raise KeyError(conversation_id)
        updated = self.get_conversation(conversation_id)
        assert updated is not None
        return updated

    def delete_conversation(self, conversation_id: str) -> None:
        with self._write() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,))

    @staticmethod
    def _row_to_conversation(row: sqlite3.Row) -> ConversationRecord:
        return ConversationRecord(
            conversation_id=row["conversation_id"],
            title=row["title"],
            selected_document_ids=json.loads(row["selected_document_ids"]),
            retrieval_mode=row["retrieval_mode"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    # --- messages ---------------------------------------------------------

    def add_message(self, record: ConversationMessageRecord) -> ConversationMessageRecord:
        with self._write() as conn:
            conn.execute(
                """INSERT INTO messages (message_id, conversation_id, role, content, created_at,
                       status, retrieval_mode, selected_document_ids, citations, stage_timings,
                       grounding, model_tag, model_digest, provider, error_code)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.message_id,
                    record.conversation_id,
                    record.role,
                    record.content,
                    record.created_at.isoformat(),
                    record.status,
                    record.retrieval_mode,
                    json.dumps(record.selected_document_ids),
                    json.dumps(record.citations),
                    json.dumps(record.stage_timings),
                    json.dumps(record.grounding),
                    record.model_tag,
                    record.model_digest,
                    record.provider,
                    record.error_code,
                ),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                (utc_now().isoformat(), record.conversation_id),
            )
        return record

    def get_message(self, message_id: str) -> ConversationMessageRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM messages WHERE message_id = ?", (message_id,)).fetchone()
        return self._row_to_message(row) if row else None

    def list_messages(self, conversation_id: str) -> list[ConversationMessageRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at, rowid",
                (conversation_id,),
            ).fetchall()
        return [self._row_to_message(r) for r in rows]

    def update_message(self, message_id: str, **fields: Any) -> ConversationMessageRecord:
        allowed = {
            "content",
            "status",
            "retrieval_mode",
            "selected_document_ids",
            "citations",
            "stage_timings",
            "grounding",
            "model_tag",
            "model_digest",
            "provider",
            "error_code",
        }
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ValueError(f"unknown message field(s): {unknown}")

        json_fields = {"selected_document_ids", "citations", "stage_timings", "grounding"}
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            assignments.append(f"{key} = ?")
            values.append(json.dumps(value) if key in json_fields else value)
        values.append(message_id)

        with self._write() as conn:
            cursor = conn.execute(
                f"UPDATE messages SET {', '.join(assignments)} WHERE message_id = ?", values
            )
            if cursor.rowcount == 0:
                raise KeyError(message_id)
        updated = self.get_message(message_id)
        assert updated is not None
        return updated

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> ConversationMessageRecord:
        return ConversationMessageRecord(
            message_id=row["message_id"],
            conversation_id=row["conversation_id"],
            role=row["role"],
            content=row["content"],
            created_at=datetime.fromisoformat(row["created_at"]),
            status=row["status"],
            retrieval_mode=row["retrieval_mode"],
            selected_document_ids=json.loads(row["selected_document_ids"]),
            citations=json.loads(row["citations"]),
            stage_timings=json.loads(row["stage_timings"]),
            grounding=json.loads(row["grounding"]),
            model_tag=row["model_tag"],
            model_digest=row["model_digest"],
            provider=row["provider"],
            error_code=row["error_code"],
        )

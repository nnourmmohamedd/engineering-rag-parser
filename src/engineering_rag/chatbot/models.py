"""Durable registry data contracts: documents, ingestion jobs, conversations.

These are the shapes persisted in SQLite and returned (via the API schemas in
``chatbot/schemas.py``) to the frontend. They are deliberately separate from
the HTTP layer's request/response models so a storage detail cannot leak into
the public API by accident.

Provenance fields (``parser_run_id``, ``chunk_run_id``, ``index_version``,
``source_sha256``) are what make a citation independently checkable months
later, so they are recorded even when a run ultimately fails -- failure
evidence is preserved, never discarded.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .states import DocumentStatus, JobStage, JobState, JobType

__all__ = [
    "REGISTRY_SCHEMA_VERSION",
    "ConversationMessageRecord",
    "ConversationRecord",
    "DocumentRecord",
    "IngestionJobRecord",
    "StageTiming",
    "utc_now",
]

#: Bumped whenever the persisted SQLite schema changes shape. `storage.py`
#: refuses to open a database written by a newer version than it understands,
#: rather than silently misreading columns.
REGISTRY_SCHEMA_VERSION = 1


def utc_now() -> datetime:
    """Timezone-aware UTC now. Never naive: these timestamps cross a JSON boundary."""
    return datetime.now(timezone.utc)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StageTiming(_Model):
    """Wall-clock duration of one completed pipeline stage."""

    stage: JobStage
    duration_s: float = Field(ge=0.0)


class DocumentRecord(_Model):
    """One uploaded document and everything known about its processing."""

    document_id: str
    #: Sanitized via `utils.paths.safe_filename` -- never the raw client value.
    stored_filename: str
    #: The original name as supplied, retained for display only. Never used to
    #: build a filesystem path; treat as untrusted text in the UI too.
    display_name: str
    sha256: str
    media_type: str
    byte_size: int = Field(ge=0)
    page_count: int | None = None

    parser_profile: str
    status: DocumentStatus = DocumentStatus.UPLOADED
    version: int = Field(default=1, ge=1)

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    #: Repository-relative paths. Absolute paths are never persisted or served.
    source_path: str | None = None
    parser_run_id: str | None = None
    chunk_run_id: str | None = None
    index_version: str | None = None

    total_chunks: int | None = None
    warnings: list[str] = Field(default_factory=list)
    validation_summary: dict[str, Any] = Field(default_factory=dict)

    deleted_at: datetime | None = None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class IngestionJobRecord(_Model):
    """One unit of ingestion work and its complete, durable evidence trail."""

    job_id: str
    document_id: str
    job_type: JobType = JobType.INGEST
    state: JobState = JobState.QUEUED
    stage: JobStage = JobStage.QUEUED
    progress: float = Field(default=0.0, ge=0.0, le=1.0)

    attempt: int = Field(default=1, ge=1)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    stage_timings: list[StageTiming] = Field(default_factory=list)

    #: A stable machine-readable code (e.g. ``PARSER_VALIDATION_FAILED``) plus
    #: a message already scrubbed of filesystem paths and internals.
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False

    cancel_requested: bool = False
    correlation_id: str | None = None

    @property
    def is_terminal(self) -> bool:
        from .states import TERMINAL_JOB_STATES

        return self.state in TERMINAL_JOB_STATES


class ConversationMessageRecord(_Model):
    """One message in a conversation.

    An assistant message stores the *validated* answer plus its immutable
    citation payload. Citations are snapshotted at answer time so deleting a
    document later cannot retroactively falsify a historical answer -- the UI
    marks such a source unavailable instead of rewriting what was cited.
    """

    message_id: str
    conversation_id: str
    role: str  # "user" | "assistant"
    content: str
    created_at: datetime = Field(default_factory=utc_now)

    status: str | None = None
    retrieval_mode: str | None = None
    selected_document_ids: list[str] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    stage_timings: dict[str, float] = Field(default_factory=dict)
    grounding: dict[str, Any] = Field(default_factory=dict)
    model_tag: str | None = None
    model_digest: str | None = None
    provider: str | None = None
    error_code: str | None = None


class ConversationRecord(_Model):
    """A named chat session bound to an explicit document selection."""

    conversation_id: str
    title: str
    selected_document_ids: list[str] = Field(default_factory=list)
    retrieval_mode: str = "vector"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

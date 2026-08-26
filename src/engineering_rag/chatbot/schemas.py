"""HTTP request/response schemas.

Kept separate from ``chatbot/models.py`` so a storage detail cannot leak into
the public API by accident: the registry may gain a column without that
column appearing in a response, and a response may reshape without a
migration. FastAPI generates the OpenAPI document from these.

Nothing here ever carries an absolute filesystem path, a traceback, or an
internal module name -- see ``ErrorEnvelope`` and ``chatbot/errors.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import ConversationMessageRecord, ConversationRecord, DocumentRecord, IngestionJobRecord
from .states import DocumentStatus, JobStage, JobState

__all__ = [
    "AskRequest",
    "CapabilitiesResponse",
    "ConversationCreateRequest",
    "ConversationDetailResponse",
    "ConversationSummary",
    "ConversationUpdateRequest",
    "DocumentDetailResponse",
    "DocumentPreviewResponse",
    "DocumentSummary",
    "ErrorEnvelope",
    "ErrorPayload",
    "HealthResponse",
    "JobSummary",
    "MessageResponse",
    "ParserProfileInfo",
    "SystemStatusResponse",
    "UploadResponse",
]


class _Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- errors ---------------------------------------------------------------


class ErrorPayload(_Schema):
    """A typed, user-safe error. The frontend branches on ``code``, never on text."""

    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Safe, user-facing explanation. Never a traceback or path.")
    retryable: bool = Field(description="Whether repeating the same request could plausibly succeed.")
    correlation_id: str | None = Field(
        default=None, description="Ties this response to the server log entry."
    )


class ErrorEnvelope(_Schema):
    error: ErrorPayload


# --- system ---------------------------------------------------------------


class DependencyStatus(_Schema):
    name: str
    available: bool
    detail: str = ""


class HealthResponse(_Schema):
    status: Literal["ok"] = "ok"
    version: str


class ParserProfileInfo(_Schema):
    """A parser profile discovered from the backend, never hard-coded in the UI."""

    id: str
    label: str
    description: str


class CapabilitiesResponse(_Schema):
    """What this backend can actually do, so the UI never advertises more."""

    version: str
    parser_profiles: list[ParserProfileInfo]
    retrieval_modes: list[str]
    default_retrieval_mode: str
    accepted_extensions: list[str]
    accepted_media_types: list[str]
    max_upload_bytes: int
    max_pages: int
    provider: str
    model_tag: str | None = None
    model_digest: str | None = None
    generation_is_cpu_bound: bool = Field(
        default=True,
        description="True when generation runs locally on CPU, so the UI can warn about latency.",
    )


class SystemStatusResponse(_Schema):
    version: str
    dependencies: list[DependencyStatus]
    documents_total: int
    documents_ready: int
    jobs_active: int
    worker_running: bool
    #: Abbreviated (never absolute) so the UI can show where state lives
    #: without publishing the machine's directory layout.
    data_root_label: str


# --- documents ------------------------------------------------------------


class DocumentSummary(_Schema):
    document_id: str
    display_name: str
    status: DocumentStatus
    parser_profile: str
    byte_size: int
    page_count: int | None
    total_chunks: int | None
    warning_count: int
    created_at: datetime
    updated_at: datetime
    sha256: str

    @classmethod
    def from_record(cls, record: DocumentRecord) -> DocumentSummary:
        return cls(
            document_id=record.document_id,
            display_name=record.display_name,
            status=record.status,
            parser_profile=record.parser_profile,
            byte_size=record.byte_size,
            page_count=record.page_count,
            total_chunks=record.total_chunks,
            warning_count=len(record.warnings),
            created_at=record.created_at,
            updated_at=record.updated_at,
            sha256=record.sha256,
        )


class JobSummary(_Schema):
    job_id: str
    document_id: str
    job_type: str
    state: JobState
    stage: JobStage
    progress: float
    attempt: int
    started_at: datetime | None
    finished_at: datetime | None
    stage_timings: list[dict[str, Any]]
    error_code: str | None
    error_message: str | None
    retryable: bool
    cancel_requested: bool

    @classmethod
    def from_record(cls, record: IngestionJobRecord) -> JobSummary:
        return cls(
            job_id=record.job_id,
            document_id=record.document_id,
            job_type=record.job_type.value,
            state=record.state,
            stage=record.stage,
            progress=record.progress,
            attempt=record.attempt,
            started_at=record.started_at,
            finished_at=record.finished_at,
            stage_timings=[t.model_dump(mode="json") for t in record.stage_timings],
            error_code=record.error_code,
            error_message=record.error_message,
            retryable=record.retryable,
            cancel_requested=record.cancel_requested,
        )


class DocumentDetailResponse(_Schema):
    document: DocumentSummary
    warnings: list[str]
    validation_summary: dict[str, Any]
    parser_run_id: str | None
    chunk_run_id: str | None
    index_version: str | None
    jobs: list[JobSummary]


class DocumentPreviewResponse(_Schema):
    document_id: str
    display_name: str
    #: Extracted Markdown. Untrusted document-derived text: the frontend must
    #: render it with raw HTML disabled/sanitised.
    markdown: str
    truncated: bool
    total_characters: int


class UploadResponse(_Schema):
    document: DocumentSummary
    job: JobSummary | None
    duplicate_of: str | None = Field(
        default=None,
        description="Set when this file's SHA-256 matched an existing document instead of creating one.",
    )


# --- conversations --------------------------------------------------------


class ConversationCreateRequest(_Schema):
    title: str = Field(default="New conversation", max_length=200)
    selected_document_ids: list[str] = Field(default_factory=list)
    retrieval_mode: str = "vector"


class ConversationUpdateRequest(_Schema):
    title: str | None = Field(default=None, max_length=200)
    selected_document_ids: list[str] | None = None
    retrieval_mode: str | None = None


class ConversationSummary(_Schema):
    conversation_id: str
    title: str
    selected_document_ids: list[str]
    retrieval_mode: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: ConversationRecord) -> ConversationSummary:
        return cls(
            conversation_id=record.conversation_id,
            title=record.title,
            selected_document_ids=record.selected_document_ids,
            retrieval_mode=record.retrieval_mode,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class CitationInfo(_Schema):
    citation_id: str
    chunk_id: str | None = None
    document_id: str | None = None
    source_filename: str | None = None
    page_numbers: list[int] = Field(default_factory=list)
    section_title: str | None = None
    supporting_quote: str | None = None
    content_hash: str | None = None
    #: True when the cited document has since been deleted. The citation is
    #: never rewritten -- history stays honest, the UI just marks it stale.
    source_available: bool = True


class MessageResponse(_Schema):
    message_id: str
    conversation_id: str
    role: str
    content: str
    created_at: datetime
    status: str | None
    retrieval_mode: str | None
    selected_document_ids: list[str]
    citations: list[CitationInfo]
    stage_timings: dict[str, float]
    grounding: dict[str, Any]
    model_tag: str | None
    model_digest: str | None
    provider: str | None
    error_code: str | None

    @classmethod
    def from_record(
        cls, record: ConversationMessageRecord, *, available_document_ids: set[str] | None = None
    ) -> MessageResponse:
        citations: list[CitationInfo] = []
        for raw in record.citations:
            # Stored citations are always plain dicts (they round-trip through
            # JSON in SQLite); unknown keys from an older record are dropped
            # rather than raising, so history stays readable across upgrades.
            info = CitationInfo.model_validate(
                {k: v for k, v in raw.items() if k in CitationInfo.model_fields}
            )
            if available_document_ids is not None and info.document_id is not None:
                info = info.model_copy(
                    update={"source_available": info.document_id in available_document_ids}
                )
            citations.append(info)
        return cls(
            message_id=record.message_id,
            conversation_id=record.conversation_id,
            role=record.role,
            content=record.content,
            created_at=record.created_at,
            status=record.status,
            retrieval_mode=record.retrieval_mode,
            selected_document_ids=record.selected_document_ids,
            citations=citations,
            stage_timings=record.stage_timings,
            grounding=record.grounding,
            model_tag=record.model_tag,
            model_digest=record.model_digest,
            provider=record.provider,
            error_code=record.error_code,
        )


class ConversationDetailResponse(_Schema):
    conversation: ConversationSummary
    messages: list[MessageResponse]


class AskRequest(_Schema):
    query: str = Field(min_length=1, max_length=4000)
    selected_document_ids: list[str] = Field(
        description="Must be non-empty: an empty selection is refused, never widened to everything."
    )
    retrieval_mode: str = "vector"
    top_k: int | None = Field(default=None, ge=1, le=50)

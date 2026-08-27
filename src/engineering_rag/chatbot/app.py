"""FastAPI application: the local chatbot's HTTP surface.

This is the ``api`` tier. It contains no document-processing logic -- every
route delegates to the registry, the worker/orchestrator, or the answering
service, which in turn call the existing production pipelines.

Security posture for this milestone (see ``docs/chatbot/SECURITY.md``):

- binds to ``127.0.0.1`` by default;
- CORS is restricted to the configured frontend origins, never ``*``;
- no authentication, because this is explicitly single-user local software --
  exposing it remotely requires authentication and HTTPS in front of it first;
- every error goes through :func:`translate_exception`, so no traceback,
  filesystem path or internal module name reaches a client.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from engineering_rag import __version__
from engineering_rag.chatbot.answering import (
    RETRIEVAL_MODES,
    GroundedAnsweringService,
    resolve_selection,
)
from engineering_rag.chatbot.config import ChatbotConfig, load_chatbot_config
from engineering_rag.chatbot.errors import ChatbotError, ErrorCode, translate_exception
from engineering_rag.chatbot.ingestion import IngestionOrchestrator
from engineering_rag.chatbot.models import (
    ConversationMessageRecord,
    ConversationRecord,
    DocumentRecord,
    utc_now,
)
from engineering_rag.chatbot.schemas import (
    AskRequest,
    CapabilitiesResponse,
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationSummary,
    ConversationUpdateRequest,
    DependencyStatus,
    DocumentDetailResponse,
    DocumentPreviewResponse,
    DocumentSummary,
    ErrorEnvelope,
    ErrorPayload,
    HealthResponse,
    JobSummary,
    MessageResponse,
    ParserProfileInfo,
    SystemStatusResponse,
)
from engineering_rag.chatbot.states import ACTIVE_JOB_STATES, DocumentStatus, JobType
from engineering_rag.chatbot.storage import Registry, new_id
from engineering_rag.chatbot.uploads import (
    ACCEPTED_EXTENSIONS,
    ACCEPTED_MEDIA_TYPES,
    UploadLimits,
    UploadRejected,
    discard_staged_upload,
    promote_staged_upload,
    stage_upload,
)
from engineering_rag.chatbot.worker import IngestionWorker

__all__ = ["create_app"]

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"

#: Human-readable descriptions for the parser profiles the backend supports.
#: Surfaced through /capabilities so the UI never hard-codes a list that could
#: drift from `services/parser/config.Profile`.
_PROFILE_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "default": ("Default", "Balanced settings for ordinary digitally-generated PDFs."),
    "high_fidelity": (
        "High fidelity",
        "Slower, more thorough extraction. Use for complex tables and layouts.",
    ),
    "scanned": ("Scanned / OCR", "For image-only or scanned PDFs. Runs OCR; noticeably slower."),
    "auto": ("Automatic", "Inspects the document and picks a suitable profile itself."),
}


def _error_response(exc: BaseException, correlation_id: str | None = None) -> JSONResponse:
    translated = translate_exception(exc)
    envelope = ErrorEnvelope(
        error=ErrorPayload(
            code=translated.code,
            message=translated.message,
            retryable=translated.retryable,
            correlation_id=correlation_id,
        )
    )
    return JSONResponse(status_code=translated.http_status, content=envelope.model_dump())


def create_app(
    config: ChatbotConfig | None = None,
    *,
    registry: Registry | None = None,
    worker: IngestionWorker | None = None,
    answering: GroundedAnsweringService | None = None,
    orchestrator: IngestionOrchestrator | None = None,
    start_worker: bool = True,
) -> FastAPI:
    """Build the application. Every collaborator is injectable, so tests need no real models.

    ``orchestrator`` (when the caller doesn't already supply a fully-built
    ``worker``) is shared between the worker and the delete endpoint, so an
    injected fake pipeline applies consistently to every mutation path --
    delete must not fall back to a fresh, real-pipeline orchestrator.
    """
    settings = config or load_chatbot_config()
    store = registry or Registry(settings.storage.database_path)
    shared_orchestrator = orchestrator or IngestionOrchestrator(config=settings, registry=store)
    ingestion_worker = worker or IngestionWorker(
        config=settings, registry=store, orchestrator=shared_orchestrator
    )
    answer_service = answering or GroundedAnsweringService(config=settings, registry=store)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Startup recovery happens inside the worker: any job left mid-flight
        # by a crash becomes INTERRUPTED, and its document stays unsearchable.
        if start_worker:
            ingestion_worker.start()
        try:
            yield
        finally:
            if start_worker:
                ingestion_worker.stop()
            store.close()

    app = FastAPI(
        title="Engineering RAG Chatbot",
        version=__version__,
        description=(
            "Local document-ingestion RAG chatbot. Single-user software with no "
            "authentication: bind to loopback only."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.server.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    app.state.config = settings
    app.state.registry = store
    app.state.worker = ingestion_worker
    app.state.answering = answer_service

    # --- middleware & error handling -------------------------------------

    @app.middleware("http")
    async def add_correlation_and_security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        correlation_id = new_id()
        request.state.correlation_id = correlation_id
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 - the last line of defence
            logger.exception("Unhandled error (correlation_id=%s)", correlation_id)
            response = _error_response(exc, correlation_id)
        response.headers["X-Correlation-ID"] = correlation_id
        # This API serves JSON to a local SPA; it should never be framed,
        # sniffed into another type, or referred onward.
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(ChatbotError)
    async def handle_chatbot_error(request: Request, exc: ChatbotError) -> JSONResponse:  # type: ignore[no-untyped-def]
        return _error_response(exc, getattr(request.state, "correlation_id", None))

    @app.exception_handler(UploadRejected)
    async def handle_upload_rejected(request: Request, exc: UploadRejected) -> JSONResponse:  # type: ignore[no-untyped-def]
        envelope = ErrorEnvelope(
            error=ErrorPayload(
                code=exc.code,
                message=exc.message,
                retryable=False,
                correlation_id=getattr(request.state, "correlation_id", None),
            )
        )
        return JSONResponse(status_code=422, content=envelope.model_dump())

    # --- system -----------------------------------------------------------

    @app.get(f"{API_PREFIX}/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        """Liveness only: the process is up. Says nothing about dependencies."""
        return HealthResponse(version=__version__)

    @app.get(f"{API_PREFIX}/ready", tags=["system"])
    def ready() -> dict[str, Any]:
        """Readiness: the registry is reachable and the worker is draining."""
        store.list_documents()
        return {"status": "ready", "worker_running": ingestion_worker.is_running}

    @app.get(f"{API_PREFIX}/capabilities", response_model=CapabilitiesResponse, tags=["system"])
    def capabilities() -> CapabilitiesResponse:
        """What this backend genuinely supports, so the UI advertises nothing more."""
        from engineering_rag.services.parser.config import Profile

        profiles = [
            ParserProfileInfo(
                id=profile.value,
                label=_PROFILE_DESCRIPTIONS.get(profile.value, (profile.value, ""))[0],
                description=_PROFILE_DESCRIPTIONS.get(profile.value, ("", ""))[1],
            )
            for profile in Profile
        ]
        model_tag, model_digest = _model_identity(settings)
        return CapabilitiesResponse(
            version=__version__,
            parser_profiles=profiles,
            retrieval_modes=list(RETRIEVAL_MODES),
            default_retrieval_mode=settings.default_retrieval_mode,
            accepted_extensions=sorted(ACCEPTED_EXTENSIONS),
            accepted_media_types=sorted(ACCEPTED_MEDIA_TYPES),
            max_upload_bytes=settings.storage.max_upload_bytes,
            max_pages=settings.storage.max_pages,
            provider="ollama",
            model_tag=model_tag,
            model_digest=model_digest,
        )

    @app.get(f"{API_PREFIX}/system/status", response_model=SystemStatusResponse, tags=["system"])
    def system_status() -> SystemStatusResponse:
        documents = store.list_documents()
        active = store.list_jobs(states=sorted(ACTIVE_JOB_STATES, key=lambda s: s.value))
        return SystemStatusResponse(
            version=__version__,
            dependencies=_dependency_statuses(settings),
            documents_total=len(documents),
            documents_ready=sum(1 for d in documents if d.status is DocumentStatus.READY),
            jobs_active=len(active),
            worker_running=ingestion_worker.is_running,
            # Abbreviated on purpose: enough to orient the user, not enough to
            # publish the machine's directory layout.
            data_root_label=str(settings.storage.root),
        )

    # --- documents --------------------------------------------------------

    @app.post(f"{API_PREFIX}/documents", tags=["documents"], status_code=201)
    async def upload_document(
        file: Annotated[UploadFile, File(description="A PDF document.")],
        parser_profile: Annotated[str, Form()] = "default",
        force_new_version: Annotated[bool, Form()] = False,
    ) -> Any:
        """Accept one PDF, validate it, and queue it for ingestion."""
        from engineering_rag.services.parser.config import Profile

        try:
            Profile(parser_profile)
        except ValueError:
            raise ChatbotError(
                ErrorCode.UPLOAD_REJECTED,
                f"Unknown parser profile {parser_profile!r}.",
                http_status=422,
            ) from None

        document_id = new_id()
        chunks: list[bytes] = []
        while block := await file.read(1024 * 1024):
            chunks.append(block)

        staged = stage_upload(
            chunks,
            filename=file.filename,
            staging_dir=settings.storage.staging_dir,
            document_id=document_id,
            declared_media_type=file.content_type,
            limits=UploadLimits(
                max_bytes=settings.storage.max_upload_bytes, max_pages=settings.storage.max_pages
            ),
        )

        # Duplicate policy is explicit rather than "last write wins".
        if not force_new_version:
            for existing in store.find_documents_by_sha256(staged.sha256):
                if existing.status is DocumentStatus.READY:
                    discard_staged_upload(staged)
                    return {
                        "document": DocumentSummary.from_record(existing).model_dump(mode="json"),
                        "job": None,
                        "duplicate_of": existing.document_id,
                    }
                active = [
                    j
                    for j in store.list_jobs(document_id=existing.document_id)
                    if j.state in ACTIVE_JOB_STATES
                ]
                if active:
                    discard_staged_upload(staged)
                    return {
                        "document": DocumentSummary.from_record(existing).model_dump(mode="json"),
                        "job": JobSummary.from_record(active[0]).model_dump(mode="json"),
                        "duplicate_of": existing.document_id,
                    }

        destination = promote_staged_upload(staged, settings.storage.uploads_dir)
        record = store.create_document(
            DocumentRecord(
                document_id=document_id,
                stored_filename=staged.stored_filename,
                display_name=staged.display_name,
                sha256=staged.sha256,
                media_type=staged.media_type,
                byte_size=staged.byte_size,
                parser_profile=parser_profile,
                source_path=str(destination),
            )
        )
        job = ingestion_worker.submit(record.document_id)
        return {
            "document": DocumentSummary.from_record(record).model_dump(mode="json"),
            "job": JobSummary.from_record(job).model_dump(mode="json"),
            "duplicate_of": None,
        }

    @app.get(f"{API_PREFIX}/documents", response_model=list[DocumentSummary], tags=["documents"])
    def list_documents(status: str | None = None) -> list[DocumentSummary]:
        records = store.list_documents()
        if status:
            records = [r for r in records if r.status.value == status]
        return [DocumentSummary.from_record(r) for r in records]

    @app.get(
        f"{API_PREFIX}/documents/{{document_id}}",
        response_model=DocumentDetailResponse,
        tags=["documents"],
    )
    def get_document(document_id: str) -> DocumentDetailResponse:
        record = _require_document(store, document_id)
        return DocumentDetailResponse(
            document=DocumentSummary.from_record(record),
            warnings=record.warnings,
            validation_summary=record.validation_summary,
            parser_run_id=record.parser_run_id,
            chunk_run_id=record.chunk_run_id,
            index_version=record.index_version,
            jobs=[JobSummary.from_record(j) for j in store.list_jobs(document_id=document_id)],
        )

    @app.get(
        f"{API_PREFIX}/documents/{{document_id}}/preview",
        response_model=DocumentPreviewResponse,
        tags=["documents"],
    )
    def preview_document(document_id: str, max_characters: int = 60_000) -> DocumentPreviewResponse:
        """Return the extracted Markdown. Untrusted text -- the UI must sanitise it."""
        record = _require_document(store, document_id)
        markdown = _read_markdown(settings, record)
        truncated = len(markdown) > max_characters
        return DocumentPreviewResponse(
            document_id=document_id,
            display_name=record.display_name,
            markdown=markdown[:max_characters],
            truncated=truncated,
            total_characters=len(markdown),
        )

    @app.post(f"{API_PREFIX}/documents/{{document_id}}/reprocess", tags=["documents"])
    def reprocess_document(document_id: str, parser_profile: str | None = None) -> JobSummary:
        record = _require_document(store, document_id)
        if parser_profile:
            from engineering_rag.services.parser.config import Profile

            try:
                Profile(parser_profile)
            except ValueError:
                raise ChatbotError(
                    ErrorCode.UPLOAD_REJECTED, f"Unknown parser profile {parser_profile!r}.", http_status=422
                ) from None
            store.update_document(document_id, parser_profile=parser_profile)
        store.update_document(document_id, version=record.version + 1)
        return JobSummary.from_record(ingestion_worker.submit(document_id, job_type=JobType.REPROCESS))

    @app.delete(f"{API_PREFIX}/documents/{{document_id}}", tags=["documents"])
    def delete_document(document_id: str) -> dict[str, Any]:
        """Soft-delete and remove from both indexes, so it can no longer be queried."""
        record = _require_document(store, document_id)
        store.update_document(document_id, status=DocumentStatus.DELETING)

        removed: list[str] = []
        try:
            removed = shared_orchestrator.rollback_document(document_id)
            shared_orchestrator._build_bm25()
        except Exception:  # noqa: BLE001 - the document is still marked deleted below
            logger.warning("Index cleanup during delete was incomplete", exc_info=True)

        store.update_document(document_id, status=DocumentStatus.DELETED, deleted_at=utc_now())
        return {
            "document_id": document_id,
            "deleted": True,
            "chunks_removed": len(removed),
            "display_name": record.display_name,
        }

    # --- jobs -------------------------------------------------------------

    @app.get(f"{API_PREFIX}/jobs/{{job_id}}", response_model=JobSummary, tags=["jobs"])
    def get_job(job_id: str) -> JobSummary:
        job = store.get_job(job_id)
        if job is None:
            raise ChatbotError(ErrorCode.JOB_NOT_FOUND, "Job not found.", http_status=404)
        return JobSummary.from_record(job)

    @app.get(f"{API_PREFIX}/jobs/{{job_id}}/events", tags=["jobs"])
    def job_events(job_id: str) -> StreamingResponse:
        """Server-sent events for one job's live progress."""
        job = store.get_job(job_id)
        if job is None:
            raise ChatbotError(ErrorCode.JOB_NOT_FOUND, "Job not found.", http_status=404)

        def event_stream() -> Iterator[str]:
            # Replay current state first, so a late subscriber is never stuck
            # showing "queued" for a job that already finished.
            current = store.get_job(job_id)
            if current is not None:
                yield _sse(
                    {
                        "type": "snapshot",
                        "job_id": job_id,
                        "document_id": current.document_id,
                        "state": current.state.value,
                        "stage": current.stage.value,
                        "progress": current.progress,
                        "error_code": current.error_code,
                    }
                )
                if current.is_terminal:
                    return
            for event in ingestion_worker.broker.stream(job_id):
                yield _sse(event)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post(f"{API_PREFIX}/jobs/{{job_id}}/retry", response_model=JobSummary, tags=["jobs"])
    def retry_job(job_id: str) -> JobSummary:
        return JobSummary.from_record(ingestion_worker.retry(job_id))

    @app.post(f"{API_PREFIX}/jobs/{{job_id}}/cancel", response_model=JobSummary, tags=["jobs"])
    def cancel_job(job_id: str) -> JobSummary:
        return JobSummary.from_record(ingestion_worker.request_cancel(job_id))

    # --- conversations ----------------------------------------------------

    @app.post(
        f"{API_PREFIX}/conversations", response_model=ConversationSummary, tags=["chat"], status_code=201
    )
    def create_conversation(payload: ConversationCreateRequest) -> ConversationSummary:
        record = store.create_conversation(
            ConversationRecord(
                conversation_id=new_id(),
                title=payload.title,
                selected_document_ids=payload.selected_document_ids,
                retrieval_mode=payload.retrieval_mode,
            )
        )
        return ConversationSummary.from_record(record)

    @app.get(f"{API_PREFIX}/conversations", response_model=list[ConversationSummary], tags=["chat"])
    def list_conversations() -> list[ConversationSummary]:
        return [ConversationSummary.from_record(c) for c in store.list_conversations()]

    @app.get(
        f"{API_PREFIX}/conversations/{{conversation_id}}",
        response_model=ConversationDetailResponse,
        tags=["chat"],
    )
    def get_conversation(conversation_id: str) -> ConversationDetailResponse:
        record = _require_conversation(store, conversation_id)
        available = {d.document_id for d in store.list_documents()}
        return ConversationDetailResponse(
            conversation=ConversationSummary.from_record(record),
            messages=[
                MessageResponse.from_record(m, available_document_ids=available)
                for m in store.list_messages(conversation_id)
            ],
        )

    @app.patch(
        f"{API_PREFIX}/conversations/{{conversation_id}}",
        response_model=ConversationSummary,
        tags=["chat"],
    )
    def update_conversation(conversation_id: str, payload: ConversationUpdateRequest) -> ConversationSummary:
        _require_conversation(store, conversation_id)
        fields = {k: v for k, v in payload.model_dump().items() if v is not None}
        if not fields:
            return ConversationSummary.from_record(_require_conversation(store, conversation_id))
        if "retrieval_mode" in fields and fields["retrieval_mode"] not in RETRIEVAL_MODES:
            raise ChatbotError(
                ErrorCode.INVALID_RETRIEVAL_MODE,
                f"Unknown retrieval mode {fields['retrieval_mode']!r}.",
                http_status=400,
            )
        return ConversationSummary.from_record(store.update_conversation(conversation_id, **fields))

    @app.delete(f"{API_PREFIX}/conversations/{{conversation_id}}", tags=["chat"])
    def delete_conversation(conversation_id: str) -> dict[str, Any]:
        _require_conversation(store, conversation_id)
        store.delete_conversation(conversation_id)
        return {"conversation_id": conversation_id, "deleted": True}

    @app.post(
        f"{API_PREFIX}/conversations/{{conversation_id}}/messages",
        response_model=list[MessageResponse],
        tags=["chat"],
    )
    def ask(
        conversation_id: str,
        payload: AskRequest,
    ) -> list[MessageResponse]:
        """Ask one question, scoped to the selected documents, and persist both messages."""
        _require_conversation(store, conversation_id)
        # Validate the selection before storing anything, so a rejected
        # question does not leave an orphaned user message behind.
        resolve_selection(store, payload.selected_document_ids)

        user_message = store.add_message(
            ConversationMessageRecord(
                message_id=new_id(),
                conversation_id=conversation_id,
                role="user",
                content=payload.query,
                selected_document_ids=payload.selected_document_ids,
                retrieval_mode=payload.retrieval_mode,
            )
        )

        outcome = answer_service.answer(
            payload.query,
            document_ids=payload.selected_document_ids,
            retrieval_mode=payload.retrieval_mode,
            top_k=payload.top_k,
        )

        assistant_message = store.add_message(
            ConversationMessageRecord(
                message_id=new_id(),
                conversation_id=conversation_id,
                role="assistant",
                content=outcome.answer,
                status=outcome.status,
                retrieval_mode=outcome.retrieval_mode,
                selected_document_ids=outcome.selected_document_ids,
                citations=outcome.citations,
                stage_timings=outcome.stage_timings,
                grounding=outcome.grounding,
                model_tag=outcome.model_tag,
                model_digest=outcome.model_digest,
                provider=outcome.provider,
                error_code=outcome.error_code,
            )
        )
        store.update_conversation(
            conversation_id,
            selected_document_ids=payload.selected_document_ids,
            retrieval_mode=payload.retrieval_mode,
        )
        available = {d.document_id for d in store.list_documents()}
        return [
            MessageResponse.from_record(user_message, available_document_ids=available),
            MessageResponse.from_record(assistant_message, available_document_ids=available),
        ]

    return app


# --- helpers ---------------------------------------------------------------


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _require_document(store: Registry, document_id: str) -> DocumentRecord:
    record = store.get_document(document_id)
    if record is None or record.is_deleted:
        raise ChatbotError(ErrorCode.DOCUMENT_NOT_FOUND, "Document not found.", http_status=404)
    return record


def _require_conversation(store: Registry, conversation_id: str) -> ConversationRecord:
    record = store.get_conversation(conversation_id)
    if record is None:
        raise ChatbotError(ErrorCode.CONVERSATION_NOT_FOUND, "Conversation not found.", http_status=404)
    return record


def _read_markdown(settings: ChatbotConfig, record: DocumentRecord) -> str:
    """Read the parser run's exported Markdown, if it exists."""
    if not record.parser_run_id:
        return ""
    run_dir = settings.parser_output_root / record.parser_run_id
    if not run_dir.is_dir():
        return ""
    for candidate in sorted(run_dir.glob("*.md")):
        try:
            return candidate.read_text(encoding="utf-8")
        except OSError:
            logger.warning("Could not read exported Markdown for a document preview")
    return ""


def _model_identity(settings: ChatbotConfig) -> tuple[str | None, str | None]:
    try:
        from engineering_rag.pipelines.answering_config import load_answering_config

        answering = load_answering_config(settings.answering_profile)
        return answering.ollama.model, answering.ollama.expected_digest
    except Exception:  # noqa: BLE001 - capabilities must still answer without a profile
        return None, None


def _dependency_statuses(settings: ChatbotConfig) -> list[DependencyStatus]:
    """Probe Ollama, Chroma and BM25 without ever raising."""
    statuses: list[DependencyStatus] = []

    try:
        from engineering_rag.clients.ollama import OllamaHTTPClient
        from engineering_rag.pipelines.answering_config import load_answering_config

        answering = load_answering_config(settings.answering_profile)
        client = OllamaHTTPClient(answering.ollama)
        reachable = client.health_check()
        statuses.append(
            DependencyStatus(
                name="ollama",
                available=reachable,
                detail=f"model {answering.ollama.model}" if reachable else "not reachable",
            )
        )
    except Exception as exc:  # noqa: BLE001
        statuses.append(DependencyStatus(name="ollama", available=False, detail=type(exc).__name__))

    try:
        from engineering_rag.pipelines.retrieval_config import load_retrieval_config
        from engineering_rag.pipelines.retrieval_pipeline import open_collection_readonly

        retrieval = load_retrieval_config(settings.retrieval_profile)
        _client, collection = open_collection_readonly(retrieval)
        statuses.append(
            DependencyStatus(name="chroma", available=True, detail=f"{collection.count()} chunk(s)")
        )
    except Exception as exc:  # noqa: BLE001
        statuses.append(DependencyStatus(name="chroma", available=False, detail=type(exc).__name__))

    try:
        from engineering_rag.pipelines.retrieval_config import load_retrieval_config

        retrieval = load_retrieval_config(settings.retrieval_profile)
        manifest = Path(retrieval.bm25.index_path) / "bm25_manifest.json"
        statuses.append(
            DependencyStatus(
                name="bm25",
                available=manifest.is_file(),
                detail="index present" if manifest.is_file() else "index not built",
            )
        )
    except Exception as exc:  # noqa: BLE001
        statuses.append(DependencyStatus(name="bm25", available=False, detail=type(exc).__name__))

    return statuses

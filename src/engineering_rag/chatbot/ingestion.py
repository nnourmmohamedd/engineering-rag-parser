"""Ingestion orchestration: drive the existing pipelines, atomically, with rollback.

This module owns *sequencing and safety*, never document processing itself.
Every stage delegates to the production entry point that already exists
(``run_parsing_pipeline``, ``run_chunking_pipeline``, ``run_indexing_pipeline``,
``build_bm25_index_pipeline``); nothing here re-implements parsing, chunking,
embedding or indexing.

The hard guarantee it provides:

    A document becomes READY only when parser and chunk gates passed, Chroma
    holds exactly the expected chunk ids for it, and the BM25 corpus agrees.

Anything less is rolled back. Because the BM25 index is *derived wholesale
from Chroma* (see ``build_bm25_index_pipeline``), the ordering that makes
rollback tractable is: snapshot BM25 -> write Chroma -> rebuild BM25 ->
reconcile -> activate. If any step after the Chroma write fails, the
document's Chroma records are deleted (scoped by ``document_id``, never a
collection wipe) and the BM25 snapshot is restored, so the previously
validated corpus survives one document's bad day.

Index mutation is serialised by :data:`_INDEX_LOCK`, so a concurrent ingest,
retry or delete cannot interleave writes and leave the two indexes
disagreeing.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engineering_rag.chatbot.config import ChatbotConfig
from engineering_rag.chatbot.errors import ChatbotError, ErrorCode, translate_exception
from engineering_rag.chatbot.models import StageTiming, utc_now
from engineering_rag.chatbot.states import (
    DocumentStatus,
    JobStage,
    JobState,
    stage_progress,
)
from engineering_rag.chatbot.storage import Registry

__all__ = [
    "IngestionCancelled",
    "IngestionOrchestrator",
    "IngestionOutcome",
    "ReconciliationReport",
    "StageReporter",
]

logger = logging.getLogger(__name__)

#: Serialises every mutation of Chroma/BM25 across the worker and any
#: API-initiated delete. Index consistency is a process-wide invariant, so the
#: lock is module-level rather than per-orchestrator.
_INDEX_LOCK = threading.RLock()


class IngestionCancelled(Exception):
    """Raised at a safe boundary when the user requested cancellation."""


@dataclass
class ReconciliationReport:
    """Whether Chroma and BM25 actually agree about one document."""

    document_id: str
    chroma_chunk_ids: list[str] = field(default_factory=list)
    bm25_chunk_ids: list[str] = field(default_factory=list)
    missing_from_bm25: list[str] = field(default_factory=list)
    missing_from_chroma: list[str] = field(default_factory=list)

    @property
    def consistent(self) -> bool:
        return not self.missing_from_bm25 and not self.missing_from_chroma and bool(self.chroma_chunk_ids)

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "chroma_chunk_count": len(self.chroma_chunk_ids),
            "bm25_chunk_count": len(self.bm25_chunk_ids),
            "missing_from_bm25": self.missing_from_bm25,
            "missing_from_chroma": self.missing_from_chroma,
            "consistent": self.consistent,
        }


@dataclass
class IngestionOutcome:
    """The result of one ingestion attempt."""

    document_id: str
    job_id: str
    succeeded: bool
    total_chunks: int = 0
    parser_run_id: str | None = None
    chunk_run_id: str | None = None
    reconciliation: ReconciliationReport | None = None
    error_code: str | None = None
    error_message: str | None = None
    stage_timings: list[StageTiming] = field(default_factory=list)


class StageReporter:
    """Persists stage/progress transitions and fans them out to live listeners.

    Progress is only ever what the backend actually reached -- there is no
    interpolation or synthetic animation, because a progress bar that moves
    while nothing happens is a lie the UI would be telling on our behalf.
    """

    def __init__(
        self,
        registry: Registry,
        job_id: str,
        *,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._registry = registry
        self._job_id = job_id
        self._on_event = on_event
        self._stage_started = time.perf_counter()
        self.timings: list[StageTiming] = []

    def enter(self, stage: JobStage) -> None:
        """Record that the job has reached ``stage``, closing out the previous one."""
        now = time.perf_counter()
        job = self._registry.get_job(self._job_id)
        if job is not None and job.stage is not stage:
            self.timings.append(StageTiming(stage=job.stage, duration_s=round(now - self._stage_started, 3)))
        self._stage_started = now

        updated = self._registry.update_job(
            self._job_id,
            stage=stage,
            progress=stage_progress(stage),
            stage_timings=self.timings,
        )
        self._emit(
            {
                "type": "stage",
                "job_id": self._job_id,
                "document_id": updated.document_id,
                "stage": stage.value,
                "state": updated.state.value,
                "progress": updated.progress,
            }
        )

    def finish_current_stage(self) -> None:
        """Close the timing of the stage in flight without moving to a new one."""
        job = self._registry.get_job(self._job_id)
        if job is None:
            return
        self.timings.append(
            StageTiming(stage=job.stage, duration_s=round(time.perf_counter() - self._stage_started, 3))
        )
        self._registry.update_job(self._job_id, stage_timings=self.timings)

    def _emit(self, event: dict[str, Any]) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(event)
        except Exception:  # noqa: BLE001 - a broken listener must never fail ingestion
            logger.warning("Progress listener raised; continuing ingestion", exc_info=True)


class IngestionOrchestrator:
    """Runs one document through the existing pipelines, or rolls back cleanly."""

    def __init__(
        self,
        *,
        config: ChatbotConfig,
        registry: Registry,
        parser_runner: Callable[..., Any] | None = None,
        chunker_runner: Callable[..., Any] | None = None,
        indexer_runner: Callable[..., Any] | None = None,
        bm25_builder: Callable[..., Any] | None = None,
        chroma_opener: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        self._registry = registry
        # Injected for tests: the real callables are imported lazily inside
        # `_default_*` so importing this module does not pull chromadb,
        # sentence-transformers and docling into the API process at startup.
        self._parser_runner = parser_runner
        self._chunker_runner = chunker_runner
        self._indexer_runner = indexer_runner
        self._bm25_builder = bm25_builder
        self._chroma_opener = chroma_opener

    # --- pipeline entry points (lazily imported real implementations) -----

    def _run_parser(self, pdf_path: Path, profile: str) -> Any:
        if self._parser_runner is not None:
            return self._parser_runner(pdf_path, profile)
        from engineering_rag.pipelines.parsing_pipeline import run_parsing_pipeline
        from engineering_rag.services.parser.config import ParserConfig, Profile

        config = ParserConfig(profile=Profile(profile))
        return run_parsing_pipeline(pdf_path, config, self._config.parser_output_root)

    def _run_chunker(self, parser_run_dir: Path) -> Any:
        if self._chunker_runner is not None:
            return self._chunker_runner(parser_run_dir)
        from engineering_rag.pipelines.chunking_pipeline import run_chunking_pipeline
        from engineering_rag.services.chunker.config import ChunkerConfig

        return run_chunking_pipeline(parser_run_dir, ChunkerConfig(), self._config.chunker_output_root)

    def _run_indexer(self, chunk_run_dir: Path) -> Any:
        if self._indexer_runner is not None:
            return self._indexer_runner(chunk_run_dir)
        from engineering_rag.pipelines.indexing_config import load_indexing_config
        from engineering_rag.pipelines.indexing_pipeline import run_indexing_pipeline

        return run_indexing_pipeline(chunk_run_dir, load_indexing_config())

    def _build_bm25(self) -> Any:
        if self._bm25_builder is not None:
            return self._bm25_builder()
        from engineering_rag.pipelines.retrieval_config import load_retrieval_config
        from engineering_rag.pipelines.retrieval_pipeline import build_bm25_index_pipeline

        config = load_retrieval_config(self._config.retrieval_profile)
        return build_bm25_index_pipeline(config, force=True)

    def _open_chroma(self) -> Any:
        if self._chroma_opener is not None:
            return self._chroma_opener()
        from engineering_rag.pipelines.retrieval_config import load_retrieval_config
        from engineering_rag.pipelines.retrieval_pipeline import open_collection_readonly

        config = load_retrieval_config(self._config.retrieval_profile)
        _client, collection = open_collection_readonly(config)
        return collection

    # --- BM25 snapshot / restore -----------------------------------------

    def _bm25_index_dir(self) -> Path:
        from engineering_rag.pipelines.retrieval_config import load_retrieval_config

        return Path(load_retrieval_config(self._config.retrieval_profile).bm25.index_path)

    def _snapshot_bm25(self, document_id: str) -> Path | None:
        """Copy the current BM25 index aside so a failure can restore it."""
        source = self._bm25_index_dir()
        if not source.is_dir():
            return None
        destination = self._config.storage.backups_dir / f"bm25-{document_id}-{int(time.time())}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
        logger.info("Snapshotted BM25 index before mutation for document_id=%s", document_id)
        return destination

    def _restore_bm25(self, snapshot: Path | None) -> None:
        if snapshot is None or not snapshot.is_dir():
            return
        target = self._bm25_index_dir()
        if target.is_dir():
            shutil.rmtree(target)
        shutil.copytree(snapshot, target)
        logger.warning("Restored BM25 index from snapshot %s", snapshot.name)

    @staticmethod
    def _discard_snapshot(snapshot: Path | None) -> None:
        if snapshot is not None and snapshot.is_dir():
            shutil.rmtree(snapshot, ignore_errors=True)

    # --- reconciliation and rollback --------------------------------------

    def reconcile(self, document_id: str) -> ReconciliationReport:
        """Confirm Chroma and BM25 hold the same chunk set for ``document_id``."""
        from engineering_rag.databases.chroma import list_document_chunk_ids

        collection = self._open_chroma()
        chroma_ids = list_document_chunk_ids(collection, document_id)

        bm25_ids: list[str] = []
        try:
            from engineering_rag.databases.bm25.index import load_bm25_index
            from engineering_rag.pipelines.retrieval_config import load_retrieval_config

            handle = load_bm25_index(load_retrieval_config(self._config.retrieval_profile).bm25)
            bm25_ids = sorted(
                record.chunk_id
                for record in handle.records
                if getattr(record, "document_id", None) == document_id
            )
        except Exception:  # noqa: BLE001 - a missing/unreadable index is a mismatch, not a crash
            logger.warning("Could not read the BM25 index during reconciliation", exc_info=True)

        chroma_set, bm25_set = set(chroma_ids), set(bm25_ids)
        return ReconciliationReport(
            document_id=document_id,
            chroma_chunk_ids=chroma_ids,
            bm25_chunk_ids=bm25_ids,
            missing_from_bm25=sorted(chroma_set - bm25_set),
            missing_from_chroma=sorted(bm25_set - chroma_set),
        )

    def rollback_document(self, document_id: str, snapshot: Path | None = None) -> list[str]:
        """Undo a partial ingestion: drop this document's Chroma records, restore BM25."""
        from engineering_rag.databases.chroma import delete_document_records

        deleted: list[str] = []
        try:
            collection = self._open_chroma()
            deleted = delete_document_records(collection, document_id)
        except Exception:  # noqa: BLE001 - rollback must not mask the original failure
            logger.error("Chroma rollback failed for document_id=%s", document_id, exc_info=True)
        self._restore_bm25(snapshot)
        return deleted

    # --- the pipeline -----------------------------------------------------

    def run(
        self,
        *,
        document_id: str,
        job_id: str,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> IngestionOutcome:
        """Process one document end to end. Never raises: failures become a recorded outcome."""
        reporter = StageReporter(self._registry, job_id, on_event=on_event)
        document = self._registry.get_document(document_id)
        if document is None:
            raise ChatbotError(ErrorCode.DOCUMENT_NOT_FOUND, "Document not found.", http_status=404)

        self._registry.update_job(job_id, state=JobState.RUNNING, started_at=utc_now())
        self._registry.update_document(document_id, status=DocumentStatus.PROCESSING)

        snapshot: Path | None = None
        chroma_written = False

        try:
            with _INDEX_LOCK:
                self._check_cancelled(job_id)
                reporter.enter(JobStage.VALIDATING)
                source = Path(document.source_path or "")
                if not source.is_file():
                    raise ChatbotError(
                        ErrorCode.PARSER_FAILED,
                        "The uploaded file is no longer available on disk.",
                        http_status=410,
                    )

                # --- parse ------------------------------------------------
                self._check_cancelled(job_id)
                reporter.enter(JobStage.PARSING)
                parser_result = self._run_parser(source, document.parser_profile)

                reporter.enter(JobStage.PARSER_VALIDATION)
                self._assert_gate_passed(
                    getattr(parser_result, "status", None),
                    ErrorCode.PARSER_VALIDATION_FAILED,
                    "The document did not pass parser validation.",
                )
                parser_run_dir = Path(parser_result.run_dir)
                self._registry.update_document(document_id, parser_run_id=parser_run_dir.name)

                # --- chunk ------------------------------------------------
                self._check_cancelled(job_id)
                reporter.enter(JobStage.CHUNKING)
                chunk_result = self._run_chunker(parser_run_dir)

                reporter.enter(JobStage.CHUNK_VALIDATION)
                self._assert_gate_passed(
                    getattr(chunk_result, "status", None),
                    ErrorCode.CHUNK_VALIDATION_FAILED,
                    "The document did not pass chunk validation.",
                )
                chunk_run_dir = Path(chunk_result.run_dir)
                self._registry.update_document(document_id, chunk_run_id=chunk_run_dir.name)

                # --- index -------------------------------------------------
                self._check_cancelled(job_id)
                reporter.enter(JobStage.EMBEDDING)
                snapshot = self._snapshot_bm25(document_id)

                reporter.enter(JobStage.VECTOR_INDEXING)
                index_result = self._run_indexer(chunk_run_dir)
                chroma_written = True
                self._assert_gate_passed(
                    getattr(index_result, "status", None),
                    ErrorCode.VECTOR_INDEXING_FAILED,
                    "The document could not be indexed into the vector database.",
                )

                reporter.enter(JobStage.BM25_INDEXING)
                self._build_bm25()

                # --- reconcile and activate --------------------------------
                reporter.enter(JobStage.INDEX_VALIDATION)
                report = self.reconcile(document_id)
                if not report.consistent:
                    raise ChatbotError(
                        ErrorCode.INDEX_VALIDATION_FAILED,
                        "The vector and lexical indexes did not agree about this document after "
                        "processing, so it was not activated.",
                        retryable=True,
                        http_status=409,
                    )

                reporter.enter(JobStage.ACTIVATION)
                reporter.finish_current_stage()
                total_chunks = len(report.chroma_chunk_ids)
                self._registry.update_document(
                    document_id,
                    status=DocumentStatus.READY,
                    total_chunks=total_chunks,
                    index_version=str(int(time.time())),
                    validation_summary=report.as_dict(),
                )
                self._registry.update_job(
                    job_id,
                    state=JobState.READY,
                    progress=1.0,
                    finished_at=utc_now(),
                    stage_timings=reporter.timings,
                )
                self._discard_snapshot(snapshot)

            self._emit_terminal(on_event, job_id, document_id, JobState.READY)
            return IngestionOutcome(
                document_id=document_id,
                job_id=job_id,
                succeeded=True,
                total_chunks=total_chunks,
                parser_run_id=parser_run_dir.name,
                chunk_run_id=chunk_run_dir.name,
                reconciliation=report,
                stage_timings=reporter.timings,
            )

        except IngestionCancelled:
            if chroma_written:
                self.rollback_document(document_id, snapshot)
            else:
                self._discard_snapshot(snapshot)
            self._fail(
                job_id,
                document_id,
                ErrorCode.INGESTION_CANCELLED,
                "Processing was cancelled.",
                JobState.CANCELLED,
                reporter,
                retryable=True,
            )
            self._emit_terminal(on_event, job_id, document_id, JobState.CANCELLED)
            return IngestionOutcome(
                document_id=document_id,
                job_id=job_id,
                succeeded=False,
                error_code=ErrorCode.INGESTION_CANCELLED,
                error_message="Processing was cancelled.",
                stage_timings=reporter.timings,
            )

        except Exception as exc:  # noqa: BLE001 - every failure becomes a recorded outcome
            translated = translate_exception(exc)
            logger.error(
                "Ingestion failed for document_id=%s job_id=%s: %s",
                document_id,
                job_id,
                translated.code,
                exc_info=True,
            )
            if chroma_written:
                self.rollback_document(document_id, snapshot)
            else:
                self._discard_snapshot(snapshot)
            self._fail(
                job_id,
                document_id,
                translated.code,
                translated.message,
                JobState.FAILED,
                reporter,
                retryable=translated.retryable,
            )
            self._emit_terminal(on_event, job_id, document_id, JobState.FAILED, translated.code)
            return IngestionOutcome(
                document_id=document_id,
                job_id=job_id,
                succeeded=False,
                error_code=translated.code,
                error_message=translated.message,
                stage_timings=reporter.timings,
            )

    # --- helpers -----------------------------------------------------------

    def _check_cancelled(self, job_id: str) -> None:
        """Cancellation is honoured only between stages -- never mid-write."""
        job = self._registry.get_job(job_id)
        if job is not None and job.cancel_requested:
            raise IngestionCancelled()

    @staticmethod
    def _assert_gate_passed(status: Any, code: str, message: str) -> None:
        """A validation gate must pass; a FAIL stops the pipeline immediately."""
        value = getattr(status, "value", status)
        if value is None:
            return
        if str(value).upper() == "FAIL":
            raise ChatbotError(code, message, retryable=False, http_status=422)

    def _fail(
        self,
        job_id: str,
        document_id: str,
        code: str,
        message: str,
        state: JobState,
        reporter: StageReporter,
        *,
        retryable: bool,
    ) -> None:
        reporter.finish_current_stage()
        self._registry.update_job(
            job_id,
            state=state,
            finished_at=utc_now(),
            error_code=code,
            error_message=message,
            retryable=retryable,
            stage_timings=reporter.timings,
        )
        document = self._registry.get_document(document_id)
        if document is not None and document.status is not DocumentStatus.DELETED:
            self._registry.update_document(document_id, status=DocumentStatus.FAILED)

    @staticmethod
    def _emit_terminal(
        on_event: Callable[[dict[str, Any]], None] | None,
        job_id: str,
        document_id: str,
        state: JobState,
        error_code: str | None = None,
    ) -> None:
        if on_event is None:
            return
        try:
            on_event(
                {
                    "type": "terminal",
                    "job_id": job_id,
                    "document_id": document_id,
                    "state": state.value,
                    "error_code": error_code,
                }
            )
        except Exception:  # noqa: BLE001
            logger.warning("Terminal progress listener raised", exc_info=True)

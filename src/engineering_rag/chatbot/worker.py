"""Bounded background ingestion worker and its live progress broker.

One small thread pool drains queued jobs. Concurrency defaults to 1 because
Docling conversion, BGE embedding and the cross-encoder are all
resource-heavy: running two at once on a laptop makes both slower and
increases index contention for no throughput gain.

The broker exists because progress has two audiences with different needs.
The registry is the durable record (survives a refresh or a restart); the
broker is the *live* feed an SSE connection reads. A subscriber that is slow
or has gone away must never block ingestion, so each subscriber gets a
bounded queue and events are dropped for that subscriber alone once it
overflows -- the durable record still has the truth.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Iterator
from typing import Any

from engineering_rag.chatbot.config import ChatbotConfig
from engineering_rag.chatbot.errors import ChatbotError, ErrorCode
from engineering_rag.chatbot.ingestion import IngestionOrchestrator
from engineering_rag.chatbot.models import IngestionJobRecord, utc_now
from engineering_rag.chatbot.states import DocumentStatus, JobState, JobType, is_retryable_state
from engineering_rag.chatbot.storage import Registry, new_id

__all__ = ["IngestionWorker", "ProgressBroker"]

logger = logging.getLogger(__name__)

#: Per-subscriber buffer. Generous enough for a normal ingestion's event
#: count, small enough that a dead browser tab cannot grow without bound.
_SUBSCRIBER_QUEUE_SIZE = 256


class ProgressBroker:
    """Fans ingestion events out to live subscribers, without ever blocking the worker."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: dict[str, list[queue.Queue[dict[str, Any] | None]]] = {}

    def publish(self, event: dict[str, Any]) -> None:
        job_id = str(event.get("job_id", ""))
        with self._lock:
            listeners = list(self._subscribers.get(job_id, ()))
        for listener in listeners:
            try:
                listener.put_nowait(event)
            except queue.Full:
                # Drop for this subscriber only. The registry remains the
                # source of truth, so a reconnect resynchronises.
                logger.debug("Dropping progress event for a saturated subscriber (job_id=%s)", job_id)

    def subscribe(self, job_id: str) -> queue.Queue[dict[str, Any] | None]:
        listener: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=_SUBSCRIBER_QUEUE_SIZE)
        with self._lock:
            self._subscribers.setdefault(job_id, []).append(listener)
        return listener

    def unsubscribe(self, job_id: str, listener: queue.Queue[dict[str, Any] | None]) -> None:
        with self._lock:
            listeners = self._subscribers.get(job_id)
            if not listeners:
                return
            if listener in listeners:
                listeners.remove(listener)
            if not listeners:
                self._subscribers.pop(job_id, None)

    def close(self, job_id: str) -> None:
        """Signal end-of-stream to every subscriber of ``job_id``."""
        with self._lock:
            listeners = list(self._subscribers.get(job_id, ()))
        for listener in listeners:
            try:
                listener.put_nowait(None)
            except queue.Full:
                logger.debug("Could not deliver end-of-stream sentinel (job_id=%s)", job_id)

    def stream(self, job_id: str) -> Iterator[dict[str, Any]]:
        """Yield live events for ``job_id`` until the job reaches a terminal state."""
        listener = self.subscribe(job_id)
        try:
            while True:
                event = listener.get()
                if event is None:
                    return
                yield event
                if event.get("type") == "terminal":
                    return
        finally:
            self.unsubscribe(job_id, listener)


class IngestionWorker:
    """Drains queued ingestion jobs with bounded concurrency."""

    def __init__(
        self,
        *,
        config: ChatbotConfig,
        registry: Registry,
        orchestrator: IngestionOrchestrator | None = None,
        broker: ProgressBroker | None = None,
    ) -> None:
        self._config = config
        self._registry = registry
        self._orchestrator = orchestrator or IngestionOrchestrator(config=config, registry=registry)
        self.broker = broker or ProgressBroker()

        self._queue: queue.Queue[str] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._stopping = threading.Event()

    # --- lifecycle -------------------------------------------------------

    def start(self) -> None:
        """Recover interrupted work, requeue nothing implicitly, then start draining."""
        recovered = self._registry.recover_interrupted_jobs()
        if recovered:
            logger.warning(
                "Marked %d unfinished ingestion job(s) INTERRUPTED after restart; "
                "they require an explicit retry.",
                len(recovered),
            )

        self._stopping.clear()
        for index in range(self._config.worker.concurrency):
            thread = threading.Thread(target=self._loop, name=f"ingestion-worker-{index}", daemon=True)
            thread.start()
            self._threads.append(thread)
        logger.info("Ingestion worker started with concurrency=%d", self._config.worker.concurrency)

    def stop(self, timeout: float = 5.0) -> None:
        self._stopping.set()
        for _ in self._threads:
            self._queue.put("")  # unblock any waiting worker
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads.clear()

    # --- submission -------------------------------------------------------

    def submit(self, document_id: str, *, job_type: JobType = JobType.INGEST) -> IngestionJobRecord:
        """Create a QUEUED job for ``document_id`` and hand it to the worker pool."""
        attempts = len(self._registry.list_jobs(document_id=document_id))
        job = self._registry.create_job(
            IngestionJobRecord(
                job_id=new_id(),
                document_id=document_id,
                job_type=job_type,
                attempt=attempts + 1,
                correlation_id=new_id(),
            )
        )
        self._queue.put(job.job_id)
        return job

    def retry(self, job_id: str) -> IngestionJobRecord:
        """Re-queue a failed/cancelled/interrupted job as a fresh attempt."""
        job = self._registry.get_job(job_id)
        if job is None:
            raise ChatbotError(ErrorCode.JOB_NOT_FOUND, "Job not found.", http_status=404)
        if not is_retryable_state(job.state):
            raise ChatbotError(
                ErrorCode.INVALID_STATE_TRANSITION,
                f"A job in state {job.state.value} cannot be retried.",
                http_status=409,
            )
        return self.submit(job.document_id, job_type=job.job_type)

    def request_cancel(self, job_id: str) -> IngestionJobRecord:
        """Ask a job to stop. It stops at the next safe stage boundary, never mid-write."""
        job = self._registry.get_job(job_id)
        if job is None:
            raise ChatbotError(ErrorCode.JOB_NOT_FOUND, "Job not found.", http_status=404)
        if job.is_terminal:
            raise ChatbotError(
                ErrorCode.INVALID_STATE_TRANSITION,
                "That job has already finished and cannot be cancelled.",
                http_status=409,
            )
        return self._registry.update_job(job_id, cancel_requested=True)

    # --- draining ---------------------------------------------------------

    def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                job_id = self._queue.get(timeout=self._config.worker.poll_interval_s)
            except queue.Empty:
                continue
            if not job_id or self._stopping.is_set():
                continue
            try:
                self._process(job_id)
            except Exception:  # noqa: BLE001 - one bad job must not kill the worker thread
                logger.exception("Unhandled error while processing job_id=%s", job_id)
            finally:
                self._queue.task_done()

    def _process(self, job_id: str) -> None:
        job = self._registry.get_job(job_id)
        if job is None or job.state is not JobState.QUEUED:
            return

        if job.cancel_requested:
            self._registry.update_job(
                job_id,
                state=JobState.CANCELLED,
                finished_at=utc_now(),
                error_code=ErrorCode.INGESTION_CANCELLED,
                error_message="Processing was cancelled before it started.",
                retryable=True,
            )
            self.broker.publish(
                {
                    "type": "terminal",
                    "job_id": job_id,
                    "document_id": job.document_id,
                    "state": JobState.CANCELLED.value,
                    "error_code": ErrorCode.INGESTION_CANCELLED,
                }
            )
            self.broker.close(job_id)
            self._registry.update_document(job.document_id, status=DocumentStatus.FAILED)
            return

        try:
            self._orchestrator.run(document_id=job.document_id, job_id=job_id, on_event=self.broker.publish)
        finally:
            self.broker.close(job_id)

    # --- introspection ----------------------------------------------------

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    @property
    def is_running(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Block until the queue drains. Test/dev helper -- the API never calls this."""
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.02)
        return False

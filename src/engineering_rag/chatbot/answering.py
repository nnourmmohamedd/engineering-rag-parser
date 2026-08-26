"""Grounded answering scoped to an explicit document selection.

Wraps the existing ``run_ask_pipeline`` without changing it: retrieval,
context building, generation and grounding validation all stay exactly as the
answering milestone left them. What this module adds is the *selection
boundary* -- turning "the user ticked these three documents" into a filter the
database applies at query time, and refusing anything that would widen it.

Three rules are enforced here and tested adversarially:

1. **An empty selection is refused**, never treated as "search everything".
   Silently widening scope is the worst possible default.
2. **Only READY documents are selectable.** A processing, failed, interrupted
   or deleted document cannot be queried, so a half-indexed corpus can never
   answer a question.
3. **The filter is passed down, not applied afterwards.** The selected ids
   become a ``document_id`` ``$in`` filter that Chroma and BM25 both apply
   while ranking -- see ``services/retriever/filters.py``.

The provider indirection (:class:`AnswerProvider`) exists so a future
OpenAI-backed provider can be added without touching retrieval, context,
grounding or any UI contract. Ollama is the only provider enabled; no OpenAI
code path exists and none is claimed to be tested.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from engineering_rag.chatbot.config import ChatbotConfig
from engineering_rag.chatbot.errors import ChatbotError, ErrorCode, translate_exception
from engineering_rag.chatbot.states import is_retrievable
from engineering_rag.chatbot.storage import Registry

__all__ = [
    "RETRIEVAL_MODES",
    "AnswerOutcome",
    "AnswerProvider",
    "GroundedAnsweringService",
    "resolve_selection",
]

logger = logging.getLogger(__name__)

#: The four modes the retrieval milestone shipped. Mirrors `_MODE_TOGGLES` in
#: pipelines/answering_pipeline.py; the API exposes this through /capabilities
#: rather than letting the frontend hard-code a list that could drift.
RETRIEVAL_MODES: tuple[str, ...] = ("vector", "hybrid", "vector-rerank", "hybrid-rerank")


class AnswerProvider(Protocol):
    """A generation backend. Only the Ollama-backed implementation is enabled."""

    name: str

    def answer(
        self,
        query: str,
        *,
        retrieval_mode: str,
        metadata_filters: dict[str, Any],
        top_k: int | None,
        on_event: Callable[[dict[str, Any]], None] | None,
    ) -> Any: ...


@dataclass
class AnswerOutcome:
    """One answered (or refused, or failed) question, ready to persist and return."""

    status: str
    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    retrieval_mode: str = "vector"
    selected_document_ids: list[str] = field(default_factory=list)
    stage_timings: dict[str, float] = field(default_factory=dict)
    grounding: dict[str, Any] = field(default_factory=dict)
    model_tag: str | None = None
    model_digest: str | None = None
    provider: str = "ollama"
    error_code: str | None = None
    total_latency_s: float | None = None


def resolve_selection(registry: Registry, document_ids: Sequence[str]) -> list[str]:
    """Validate a document selection, returning the ids safe to query.

    Raises rather than narrowing silently: a caller that named a document
    which is missing or not READY has a wrong mental model of what is being
    searched, and quietly answering from a smaller corpus would hide that.
    """
    if not document_ids:
        raise ChatbotError(
            ErrorCode.EMPTY_DOCUMENT_SELECTION,
            "Select at least one document to ask a question about.",
            http_status=400,
        )

    unique = list(dict.fromkeys(document_ids))
    unknown: list[str] = []
    not_ready: list[str] = []

    for document_id in unique:
        record = registry.get_document(document_id)
        if record is None or record.is_deleted:
            unknown.append(document_id)
        elif not is_retrievable(record.status):
            not_ready.append(document_id)

    if unknown:
        raise ChatbotError(
            ErrorCode.UNKNOWN_DOCUMENT_SELECTED,
            f"{len(unknown)} selected document(s) no longer exist. Refresh the document list.",
            http_status=404,
        )
    if not_ready:
        raise ChatbotError(
            ErrorCode.DOCUMENT_NOT_READY,
            f"{len(not_ready)} selected document(s) are not finished processing yet.",
            http_status=409,
        )
    return unique


class GroundedAnsweringService:
    """Answers a question strictly within a validated document selection."""

    def __init__(
        self,
        *,
        config: ChatbotConfig,
        registry: Registry,
        ask_runner: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        self._registry = registry
        # Injected in tests; the real pipeline is imported lazily so importing
        # this module does not pull chromadb/transformers into API startup.
        self._ask_runner = ask_runner

    def _run_ask(
        self,
        query: str,
        *,
        retrieval_mode: str,
        metadata_filters: dict[str, Any],
        top_k: int | None,
    ) -> Any:
        if self._ask_runner is not None:
            return self._ask_runner(
                query,
                retrieval_mode=retrieval_mode,
                metadata_filters=metadata_filters,
                top_k=top_k,
            )
        from engineering_rag.pipelines.answering_config import load_answering_config
        from engineering_rag.pipelines.answering_pipeline import run_ask_pipeline
        from engineering_rag.pipelines.retrieval_config import load_retrieval_config

        answering_config = load_answering_config(self._config.answering_profile)
        retrieval_config = load_retrieval_config(self._config.retrieval_profile)
        return run_ask_pipeline(
            query,
            answering_config,
            retrieval_config,
            retrieval_mode=retrieval_mode,
            top_k=top_k,
            metadata_filters=metadata_filters,
        )

    def answer(
        self,
        query: str,
        *,
        document_ids: Sequence[str],
        retrieval_mode: str = "vector",
        top_k: int | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> AnswerOutcome:
        """Answer ``query`` using only ``document_ids``.

        Never raises for a generation failure: an unreachable model or a
        failed grounding gate becomes a safe, explicit outcome the UI can
        show, because presenting unvalidated model text as an answer is the
        one thing this system must not do.
        """
        if retrieval_mode not in RETRIEVAL_MODES:
            raise ChatbotError(
                ErrorCode.INVALID_RETRIEVAL_MODE,
                f"Unknown retrieval mode {retrieval_mode!r}. Expected one of: {', '.join(RETRIEVAL_MODES)}.",
                http_status=400,
            )

        selected = resolve_selection(self._registry, document_ids)
        # The selection boundary: a real query-time filter, applied by Chroma
        # (native $in) and by BM25 before truncation -- not a post-hoc slice.
        metadata_filters: dict[str, Any] = {"document_id": selected}

        self._emit(on_event, {"type": "stage", "stage": "retrieval", "status": "running"})

        try:
            result = self._run_ask(
                query,
                retrieval_mode=retrieval_mode,
                metadata_filters=metadata_filters,
                top_k=top_k,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a safe outcome, never a traceback
            translated = translate_exception(exc)
            logger.warning("Answer generation failed: %s", translated.code, exc_info=True)
            self._emit(
                on_event,
                {"type": "terminal", "status": "failed", "error_code": translated.code},
            )
            return AnswerOutcome(
                status="failed",
                answer="",
                retrieval_mode=retrieval_mode,
                selected_document_ids=selected,
                error_code=translated.code,
            )

        _retrieval, _context, answer, _trace, _run_dir = result
        outcome = self._to_outcome(answer, retrieval_mode, selected)
        self._emit(
            on_event,
            {"type": "terminal", "status": outcome.status, "error_code": outcome.error_code},
        )
        return outcome

    @staticmethod
    def _to_outcome(answer: Any, retrieval_mode: str, selected: list[str]) -> AnswerOutcome:
        """Render the pipeline's AnswerResponse for the API, keeping every gate's verdict."""
        validation = getattr(answer, "validation", None)
        grounding: dict[str, Any] = {}
        if validation is not None:
            grounding = {
                "status": getattr(validation, "status", None),
                "checks_passed": list(getattr(validation, "checks_passed", []) or []),
                "checks_failed": list(getattr(validation, "checks_failed", []) or []),
                "warnings": list(getattr(validation, "warnings", []) or []),
                "citation_coverage_ratio": getattr(validation, "citation_coverage_ratio", None),
                "repair_attempted": getattr(validation, "repair_attempted", None),
            }

        citations = [
            {
                "citation_id": c.citation_id,
                "chunk_id": c.chunk_id,
                "document_id": getattr(c, "document_id", None),
                "source_filename": c.source_filename,
                "page_numbers": list(getattr(c, "page_numbers", []) or []),
                "section_title": getattr(c, "section_title", None),
                "supporting_quote": getattr(c, "supporting_quote", None),
                "content_hash": getattr(c, "content_hash", None),
            }
            for c in getattr(answer, "citations", []) or []
        ]

        status = getattr(answer, "status", "failed")
        return AnswerOutcome(
            status=status,
            # Only an `answered` response's prose is shown as an answer; every
            # other status carries its own explanatory text instead.
            answer=getattr(answer, "answer", "") or "",
            citations=citations,
            retrieval_mode=retrieval_mode,
            selected_document_ids=selected,
            stage_timings=dict(getattr(answer, "stage_latencies_s", {}) or {}),
            grounding=grounding,
            model_tag=getattr(answer, "model_tag", None),
            model_digest=getattr(answer, "model_digest", None),
            error_code=None if status in {"answered", "insufficient_evidence"} else status.upper(),
            total_latency_s=getattr(answer, "total_latency_s", None),
        )

    @staticmethod
    def _emit(on_event: Callable[[dict[str, Any]], None] | None, event: dict[str, Any]) -> None:
        if on_event is None:
            return
        try:
            on_event(event)
        except Exception:  # noqa: BLE001 - a broken listener must not fail the answer
            logger.debug("Answer progress listener raised", exc_info=True)

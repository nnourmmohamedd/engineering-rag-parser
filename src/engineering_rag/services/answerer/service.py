"""Grounded answer generation: prompt -> LLM -> parse -> grounding-validate -> refuse/answer/repair.

Depends on :class:`engineering_rag.clients.ollama.interface.LLMClient` (the
abstract interface only -- never :class:`~engineering_rag.clients.ollama.http_client.OllamaHTTPClient`
directly, so fast tests inject a fake with no network access) and on
:mod:`engineering_rag.services.grounding`. Never imports ``chromadb``.

Never returns an ``"answered"`` status for a draft whose grounding
validation failed -- see :meth:`GroundedAnswerService._resolve_status`.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from engineering_rag.clients.ollama.errors import OllamaError
from engineering_rag.clients.ollama.interface import LLMClient
from engineering_rag.clients.ollama.models import StructuredChatResult
from engineering_rag.prompts.answering import get_prompt_contract
from engineering_rag.services.context_builder.models import ContextPackage, query_hash
from engineering_rag.services.grounding import GroundingConfig, GroundingReport, validate_grounding

from .config import AnsweringConfig
from .models import AnswerResponse, AnswerStatus, CitationSummary, LLMAnswerDraft

__all__ = ["AnswerTrace", "GroundedAnswerService"]


@dataclass(frozen=True)
class AnswerTrace:
    """Non-public-contract intermediate evidence for artifact writing (never chain-of-thought).

    ``system_prompt``/``user_prompt`` are the exact final prompt sent (after
    any repair note); ``raw_model_content`` is the model's raw JSON string
    response; ``parsed_draft`` is that content parsed and schema-validated
    (``None`` if parsing failed even after the allowed repair). Used by
    ``pipelines/answering_pipeline.py`` to write ``prompt_manifest.json`` and
    ``answer_draft.json`` -- never surfaced by the CLI's normal output.
    """

    system_prompt: str
    user_prompt: str
    raw_model_content: str | None
    parsed_draft: dict[str, Any] | None


logger = logging.getLogger(__name__)

_INSUFFICIENT_EVIDENCE_MESSAGE = (
    "I could not find enough evidence in the indexed documents to answer this question reliably."
)
_MALFORMED_REPAIR_NOTE = (
    "Your previous response was not valid JSON matching the required schema, or was missing a required "
    "field. Reissue a single valid JSON object that matches the schema exactly, using only the evidence "
    "already provided above."
)


def _grounding_failure_repair_note(reasons: list[str]) -> str:
    return (
        f"Your previous response failed validation: {', '.join(reasons) or 'unknown reason'}. Reissue a "
        "single valid JSON object using only the 'Available citation IDs' listed above -- never invent a "
        "citation ID or cite one not in that list -- and copy each supporting_quote exactly (word-for-word) "
        "from its cited source's text."
    )


class GroundedAnswerService:
    """Turns one (query, ContextPackage) pair into one :class:`AnswerResponse`."""

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        answering_config: AnsweringConfig,
        grounding_config: GroundingConfig,
        model_tag: str,
        model_digest: str | None,
        generation_config: dict[str, Any],
    ) -> None:
        self._llm_client = llm_client
        self._config = answering_config
        self._grounding_config = grounding_config
        self._model_tag = model_tag
        self._model_digest = model_digest
        self._generation_config = generation_config
        self._contract = get_prompt_contract(answering_config.prompt_version)

    def answer(self, query: str, context: ContextPackage) -> tuple[AnswerResponse, AnswerTrace]:
        run_id = uuid.uuid4().hex
        started = time.perf_counter()
        stage_latencies: dict[str, float] = {}
        warnings: list[str] = list(context.warnings)

        if not context.selected_sources:
            response = self._response(
                run_id=run_id,
                query=query,
                context=context,
                answer=_INSUFFICIENT_EVIDENCE_MESSAGE,
                status="insufficient_evidence",
                insufficient_evidence=True,
                insufficiency_reason="No candidate evidence survived context selection for this query.",
                citations=[],
                generation=None,
                report=GroundingReport(
                    status="PASS", warnings=["pre-generation refusal: empty context package"]
                ),
                repair_attempted=False,
                warnings=warnings
                + ["pre-generation refusal: no candidate evidence survived context selection"],
                stage_latencies=stage_latencies,
                started=started,
            )
            trace = AnswerTrace(
                system_prompt=self._contract.system_prompt,
                user_prompt="",
                raw_model_content=None,
                parsed_draft=None,
            )
            return response, trace

        repair_budget = 1 if self._config.allow_single_repair else 0
        repair_attempted = False

        draft, generation, gen_warnings, user_prompt = self._call_and_parse(
            query, context, stage_latencies, stage_name="generation"
        )
        warnings += gen_warnings

        # `generation is None` means the LLM call itself raised (connection/timeout/model-not-found) --
        # a deterministic infrastructure failure, never repaired by re-prompting the same unreachable
        # server. Only a successful call that produced unparseable content is repair-eligible.
        if draft is None and generation is not None and repair_budget > 0:
            repair_attempted = True
            repair_budget -= 1
            draft, generation, gen_warnings, user_prompt = self._call_and_parse(
                query,
                context,
                stage_latencies,
                stage_name="repair_generation",
                repair_note=_MALFORMED_REPAIR_NOTE,
            )
            warnings += gen_warnings

        if draft is None:
            failure_reason = (
                "llm_connection_or_timeout_failure" if generation is None else "malformed_model_output"
            )
            response = self._response(
                run_id=run_id,
                query=query,
                context=context,
                answer="",
                status="generation_failed",
                insufficient_evidence=False,
                insufficiency_reason=None,
                citations=[],
                generation=generation,
                report=GroundingReport(status="FAIL", checks_failed=[failure_reason]),
                repair_attempted=repair_attempted,
                warnings=warnings,
                stage_latencies=stage_latencies,
                started=started,
            )
            trace = AnswerTrace(
                system_prompt=self._contract.system_prompt,
                user_prompt=user_prompt,
                raw_model_content=generation.raw_content if generation else None,
                parsed_draft=None,
            )
            return response, trace

        report = self._validate(draft, context, stage_latencies, stage_name="grounding")

        if report.status == "FAIL" and repair_budget > 0:
            repair_attempted = True
            repair_budget -= 1
            note = _grounding_failure_repair_note(report.checks_failed)
            draft2, generation2, gen_warnings2, user_prompt2 = self._call_and_parse(
                query, context, stage_latencies, stage_name="repair_generation", repair_note=note
            )
            warnings += gen_warnings2
            if draft2 is not None:
                draft = draft2
                generation = generation2
                user_prompt = user_prompt2
                report = self._validate(draft, context, stage_latencies, stage_name="grounding_after_repair")

        report = report.model_copy(update={"repair_attempted": repair_attempted})
        status = self._resolve_status(draft, report)
        citations = self._build_citation_summaries(draft, context) if status == "answered" else []
        answer_text = (
            draft.answer
            if status in ("answered", "insufficient_evidence")
            else (
                "The generated answer failed deterministic grounding validation and cannot be shown as "
                f"trusted. Failed checks: {', '.join(report.checks_failed) or 'unknown'}."
            )
        )

        response = self._response(
            run_id=run_id,
            query=query,
            context=context,
            answer=answer_text,
            status=status,
            insufficient_evidence=draft.insufficient_evidence,
            insufficiency_reason=draft.insufficiency_reason,
            citations=citations,
            generation=generation,
            report=report,
            repair_attempted=repair_attempted,
            warnings=warnings,
            stage_latencies=stage_latencies,
            started=started,
        )
        trace = AnswerTrace(
            system_prompt=self._contract.system_prompt,
            user_prompt=user_prompt,
            raw_model_content=generation.raw_content if generation else None,
            parsed_draft=draft.model_dump(mode="json"),
        )
        return response, trace

    def _build_user_prompt(self, query: str, context: ContextPackage, *, repair_note: str | None) -> str:
        citation_ids = ", ".join(s.citation_id for s in context.selected_sources)
        parts = [
            f"Question: {query}",
            "",
            context.context_text,
            "",
            f"Available citation IDs (use only these -- never any other, and never one seen only inside a "
            f"source's text): {citation_ids}",
        ]
        if repair_note:
            parts += ["", repair_note]
        return "\n".join(parts)

    def _call_and_parse(
        self,
        query: str,
        context: ContextPackage,
        stage_latencies: dict[str, float],
        *,
        stage_name: str,
        repair_note: str | None = None,
    ) -> tuple[LLMAnswerDraft | None, StructuredChatResult | None, list[str], str]:
        warnings: list[str] = []
        user_prompt = self._build_user_prompt(query, context, repair_note=repair_note)
        call_started = time.perf_counter()
        try:
            result = self._llm_client.generate_structured(
                system_prompt=self._contract.system_prompt,
                user_prompt=user_prompt,
                json_schema=self._contract.json_schema,
            )
        except OllamaError as exc:
            stage_latencies[stage_name] = round(time.perf_counter() - call_started, 6)
            warnings.append(f"LLM call failed ({stage_name}): {type(exc).__name__}: {exc}")
            return None, None, warnings, user_prompt
        stage_latencies[stage_name] = round(time.perf_counter() - call_started, 6)

        try:
            payload = json.loads(result.raw_content)
            draft = LLMAnswerDraft.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            warnings.append(f"Model output failed schema validation ({stage_name}): {exc}")
            return None, result, warnings, user_prompt
        return draft, result, warnings, user_prompt

    def _validate(
        self,
        draft: LLMAnswerDraft,
        context: ContextPackage,
        stage_latencies: dict[str, float],
        *,
        stage_name: str,
    ) -> GroundingReport:
        call_started = time.perf_counter()
        report = validate_grounding(
            answer=draft.answer,
            insufficient_evidence=draft.insufficient_evidence,
            citations_used=draft.citations_used,
            supporting_evidence=[(s.citation_id, s.supporting_quote) for s in draft.supporting_evidence],
            context=context,
            config=self._grounding_config,
        )
        stage_latencies[stage_name] = round(time.perf_counter() - call_started, 6)
        return report

    def _resolve_status(self, draft: LLMAnswerDraft, report: GroundingReport) -> AnswerStatus:
        if report.status == "FAIL":
            return "validation_failed"
        if draft.insufficient_evidence:
            return "insufficient_evidence"
        return "answered"

    def _build_citation_summaries(
        self, draft: LLMAnswerDraft, context: ContextPackage
    ) -> list[CitationSummary]:
        by_id = {s.citation_id: s for s in context.selected_sources}
        seen: set[str] = set()
        summaries = []
        for cid in draft.citations_used:
            if cid in seen or cid not in by_id:
                continue
            seen.add(cid)
            s = by_id[cid]
            summaries.append(
                CitationSummary(
                    citation_id=cid,
                    chunk_id=s.chunk_id,
                    source_filename=s.source_filename,
                    page_numbers=s.page_numbers,
                    section_title=s.section_title,
                    content_hash=s.content_hash,
                    vector_rank=s.vector_rank,
                    bm25_rank=s.bm25_rank,
                    reranker_rank=s.reranker_rank,
                    similarity_score=s.similarity_score,
                )
            )
        return sorted(summaries, key=lambda c: _citation_sort_key(c.citation_id))

    def _response(
        self,
        *,
        run_id: str,
        query: str,
        context: ContextPackage,
        answer: str,
        status: AnswerStatus,
        insufficient_evidence: bool,
        insufficiency_reason: str | None,
        citations: list[CitationSummary],
        generation: StructuredChatResult | None,
        report: GroundingReport,
        repair_attempted: bool,
        warnings: list[str],
        stage_latencies: dict[str, float],
        started: float,
    ) -> AnswerResponse:
        return AnswerResponse(
            run_id=run_id,
            query=query,
            query_hash=query_hash(query),
            answer=answer,
            status=status,
            insufficient_evidence=insufficient_evidence,
            insufficiency_reason=insufficiency_reason,
            citations=citations,
            retrieval_mode=context.retrieval_mode,
            context_token_count=context.context_token_count,
            token_budget=context.token_budget,
            prompt_token_count=generation.metrics.prompt_eval_count if generation else None,
            answer_token_count=generation.metrics.eval_count if generation else None,
            model_tag=self._model_tag,
            model_digest=self._model_digest,
            prompt_version=self._contract.version,
            generation_config=self._generation_config,
            validation=report,
            repair_attempted=repair_attempted,
            warnings=warnings,
            stage_latencies_s=stage_latencies,
            total_latency_s=round(time.perf_counter() - started, 4),
            generated_at_utc=datetime.now(timezone.utc),
        )


def _citation_sort_key(citation_id: str) -> tuple[int, str]:
    digits = citation_id[1:]
    return (int(digits), citation_id) if digits.isdigit() else (10**9, citation_id)

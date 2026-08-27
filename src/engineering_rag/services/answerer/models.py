"""Answerer domain contracts: the structured model draft and the stable answer response.

Deliberately independent of ``chromadb`` and ``clients.ollama`` concretely --
:class:`~engineering_rag.services.answerer.service.GroundedAnswerService`
depends on :class:`~engineering_rag.clients.ollama.interface.LLMClient` (the
interface) only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from engineering_rag.services.grounding import GroundingReport

__all__ = [
    "ANSWER_SCHEMA_VERSION",
    "AnswerResponse",
    "AnswerStatus",
    "CitationSummary",
    "LLMAnswerDraft",
    "SupportingEvidenceItem",
]

#: Bumped whenever the AnswerResponse contract changes in a way that would
#: alter what a consumer sees for identical input+config.
ANSWER_SCHEMA_VERSION = "1.0.0"

AnswerStatus = Literal["answered", "insufficient_evidence", "generation_failed", "validation_failed"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SupportingEvidenceItem(_Model):
    """One (citation_id, exact short quote) pair as declared by the model."""

    citation_id: str
    supporting_quote: str


class LLMAnswerDraft(_Model):
    """The model's raw structured output, parsed and schema-validated but not yet grounding-checked.

    Mirrors ``prompts/answering/contract.py``'s JSON Schema field-for-field.
    ``extra="forbid"`` rejects an unexpected field as a parse failure, not a
    silently-ignored one.
    """

    answer: str
    insufficient_evidence: bool
    insufficiency_reason: str | None = None
    citations_used: list[str] = Field(default_factory=list)
    supporting_evidence: list[SupportingEvidenceItem] = Field(default_factory=list)


class CitationSummary(_Model):
    """Human-readable mapping from one answer-local citation ID back to its full provenance."""

    citation_id: str
    chunk_id: str
    document_id: str | None = None
    source_filename: str | None = None
    page_numbers: list[int] = Field(default_factory=list)
    section_title: str | None = None
    content_hash: str | None = None
    vector_rank: int | None = None
    bm25_rank: int | None = None
    reranker_rank: int | None = None
    similarity_score: float | None = None


class AnswerResponse(_Model):
    """The complete, stable output contract of one grounded-answering call."""

    answer_schema_version: str = ANSWER_SCHEMA_VERSION
    run_id: str
    query: str
    query_hash: str

    answer: str
    status: AnswerStatus
    insufficient_evidence: bool
    insufficiency_reason: str | None = None
    citations: list[CitationSummary] = Field(default_factory=list)

    retrieval_mode: str
    context_token_count: int
    token_budget: int
    prompt_token_count: int | None = Field(default=None, description="Ollama's reported prompt_eval_count.")
    answer_token_count: int | None = Field(default=None, description="Ollama's reported eval_count.")

    model_tag: str
    model_digest: str | None = None
    prompt_version: str

    generation_config: dict[str, float | int | bool | str | None] = Field(default_factory=dict)
    validation: GroundingReport
    repair_attempted: bool = False

    warnings: list[str] = Field(default_factory=list)
    stage_latencies_s: dict[str, float] = Field(default_factory=dict)
    total_latency_s: float = 0.0
    generated_at_utc: datetime | None = None

"""Grounding-validation domain contracts.

Independent of ``clients/ollama`` -- these models describe the *result* of
checking one already-parsed model answer against its own
:class:`~engineering_rag.services.context_builder.models.ContextPackage`,
never the generation call itself.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "GROUNDING_SCHEMA_VERSION",
    "CitationCheckResult",
    "GroundingReport",
    "GroundingStatus",
    "QuoteCheckResult",
]

#: Bumped whenever a check's meaning or the pass/fail computation changes.
GROUNDING_SCHEMA_VERSION = "1.0.0"

GroundingStatus = Literal["PASS", "PASS_WITH_WARNINGS", "FAIL"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CitationCheckResult(_Model):
    """Whether one citation ID used or declared by the model is a real, allow-listed source."""

    citation_id: str
    valid: bool
    found_inline: bool = False
    found_in_citations_used: bool = False
    reason: str = ""


class QuoteCheckResult(_Model):
    """Whether one ``supporting_evidence`` quote is actually present in its cited source's text."""

    citation_id: str
    supporting_quote: str
    citation_is_valid: bool
    found_exact: bool
    found_normalized: bool
    reason: str = ""


class GroundingReport(_Model):
    """The complete, deterministic result of validating one model answer.

    These checks validate citation structure and extractive supporting-quote
    presence. They do NOT mathematically prove semantic entailment between a
    claim and its cited source, and a ``PASS`` status is never described as
    "fully hallucination-free" -- see
    ``docs/answering/SECURITY_AND_GROUNDING.md``.
    """

    grounding_schema_version: str = GROUNDING_SCHEMA_VERSION
    status: GroundingStatus

    citation_checks: list[CitationCheckResult] = Field(default_factory=list)
    quote_checks: list[QuoteCheckResult] = Field(default_factory=list)

    unknown_citations: list[str] = Field(default_factory=list)
    duplicate_citations: list[str] = Field(default_factory=list)
    citation_coverage_ratio: float | None = Field(
        default=None, description="Fraction of citation-qualifying sentences carrying an inline citation."
    )
    uncited_claims: list[str] = Field(
        default_factory=list,
        description="Citation-qualifying sentences (technical/factual claims) that carry zero inline "
        "citations -- the claim-level detail behind citation_coverage_ratio, not just its count.",
    )

    checks_passed: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    repair_attempted: bool = False
    repair_successful: bool | None = None

"""Validated, hashable configuration for deterministic citation/grounding validation."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["GroundingConfig"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GroundingConfig(_Frozen):
    """Deterministic, structural checks only -- see ``services/grounding/__init__.py`` for scope."""

    require_inline_citations: bool = Field(
        default=True, description="A non-refusal answer must contain at least one [S<n>] inline marker."
    )
    require_supporting_quotes: bool = Field(
        default=True, description="Every citations_used entry must have a matching supporting_evidence item."
    )
    minimum_citations_for_answer: int = Field(
        default=1, ge=0, description="Minimum distinct valid citations required for a non-refusal answer."
    )
    fail_on_unknown_citation: bool = Field(
        default=True,
        description="A citation ID not present in the ContextPackage fails validation (not a warning).",
    )
    fail_on_quote_mismatch: bool = Field(
        default=True,
        description="A supporting_quote not found (after normalization) in its cited source's text fails "
        "validation (not a warning).",
    )
    citation_coverage_warn_below: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Below this fraction of citation-qualifying sentences carrying an inline citation, add "
        "a PASS_WITH_WARNINGS warning. Heuristic only -- see validator.py docstring.",
    )
    fail_on_uncited_claim: bool = Field(
        default=True,
        description="A citation-qualifying sentence (see _qualifying_sentences) with zero inline "
        "citations fails validation, not just a coverage warning. This is claim-level, not "
        "aggregate: an answer with 5 total citations still fails here if even one qualifying "
        "sentence has none of them -- citation count alone is never treated as completeness.",
    )

    def effective_dict(self) -> dict[str, Any]:
        return json.loads(self.model_dump_json())

    def config_hash(self) -> str:
        payload = json.dumps(self.effective_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

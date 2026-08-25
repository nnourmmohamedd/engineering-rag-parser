"""Typed data contracts for the reranking stage."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

__all__ = ["RerankCandidate", "RerankResult"]


class RerankCandidate(BaseModel):
    """One (query, chunk) pair to be jointly scored by the cross-encoder."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    text: str


class RerankResult(BaseModel):
    """One candidate's outcome after cross-encoder scoring.

    ``score`` is the model's raw output (sigmoid-activated by
    ``sentence_transformers.CrossEncoder`` for this model's default
    activation) — it is a relative ranking signal, not a calibrated
    probability of relevance.
    """

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    rank: int
    score: float

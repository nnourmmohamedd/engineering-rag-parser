"""Typed interface every reranker implementation must satisfy."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import RerankCandidate, RerankResult

__all__ = ["Reranker"]


class Reranker(ABC):
    """Joint query-document scoring of a small candidate set."""

    @abstractmethod
    def rerank(self, query: str, candidates: list[RerankCandidate]) -> list[RerankResult]:
        """Score every candidate against ``query`` and return results ranked best-first.

        Args:
            query: raw query text. The BGE embedding query prefix is
                deliberately NOT applied — the cross-encoder's official
                usage does not require or expect it.
            candidates: the small pool to score (already truncated to
                ``RerankerConfig.candidate_top_k`` by the caller).

        Returns:
            One :class:`RerankResult` per input candidate, same length,
            ``rank`` 1-based and best-first by ``score`` descending.
        """

"""A deterministic, network-free fake implementing :class:`Reranker`.

Scores every candidate by the count of query tokens (lowercase, whitespace
split) that literally appear in its text — no model weights, no network.
Good enough to exercise ordering, batching-callers, and empty-candidate
handling without downloading the real cross-encoder.
"""

from __future__ import annotations

from engineering_rag.services.reranker.interface import Reranker
from engineering_rag.services.reranker.models import RerankCandidate, RerankResult

__all__ = ["FakeReranker"]


class FakeReranker(Reranker):
    def __init__(self) -> None:
        self.load_duration_s = 0.0
        self.calls: list[tuple[str, int]] = []

    def rerank(self, query: str, candidates: list[RerankCandidate]) -> list[RerankResult]:
        self.calls.append((query, len(candidates)))
        if not candidates:
            return []
        terms = set(query.lower().split())
        scored = sorted(
            ((c, float(sum(1 for t in terms if t in c.text.lower()))) for c in candidates),
            key=lambda cs: (-cs[1], cs[0].chunk_id),
        )
        return [
            RerankResult(chunk_id=c.chunk_id, rank=rank, score=score)
            for rank, (c, score) in enumerate(scored, start=1)
        ]

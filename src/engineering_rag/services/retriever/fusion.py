"""Reciprocal Rank Fusion of a vector ranking and a BM25 ranking.

RRF combines two rankings by rank position, never by mixing raw scores:
cosine similarity and a BM25 score live in unrelated, non-comparable scales
(one is bounded in ``[-1, 1]``, the other is an unbounded corpus-dependent
weight), so adding or averaging them directly would produce a number with
no defensible meaning. Rank position is the only signal both rankings share
a common scale for.

    RRF(document) = sum over each list containing it of 1 / (rrf_k + rank)

A document appearing in only one list still gets a score (from that one
list only); the "each" is a sum over lists that actually rank it, not a sum
padded with a default value for the absent list.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .models import RetrievalHit

__all__ = ["FusedHit", "reciprocal_rank_fusion"]


class FusedHit(BaseModel):
    """One deduplicated candidate after RRF, carrying every original ranking's evidence."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    rrf_score: float
    vector_rank: int | None = None
    bm25_rank: int | None = None
    hit: RetrievalHit


def reciprocal_rank_fusion(
    vector_hits: list[RetrievalHit],
    bm25_hits: list[RetrievalHit],
    *,
    rrf_k: int = 60,
) -> list[FusedHit]:
    """Fuse two rankings by chunk_id. Deterministic: ties break by ``chunk_id`` ascending.

    Every input ``RetrievalHit`` is assumed to already carry its own ``rank``
    (1-based, within that single list) — this function does not re-derive
    rank from list order, so a caller must pass hits in their original,
    already-ranked form.
    """
    by_id: dict[str, dict[str, RetrievalHit | int]] = {}

    for hit in vector_hits:
        by_id.setdefault(hit.chunk_id, {})["vector"] = hit
        by_id[hit.chunk_id]["vector_rank"] = hit.rank
    for hit in bm25_hits:
        by_id.setdefault(hit.chunk_id, {})["bm25"] = hit
        by_id[hit.chunk_id]["bm25_rank"] = hit.rank

    fused: list[FusedHit] = []
    for chunk_id, entry in by_id.items():
        vector_rank = entry.get("vector_rank")
        bm25_rank = entry.get("bm25_rank")
        vector_hit = entry.get("vector")
        bm25_hit = entry.get("bm25")
        score = 0.0
        if isinstance(vector_rank, int):
            score += 1.0 / (rrf_k + vector_rank)
        if isinstance(bm25_rank, int):
            score += 1.0 / (rrf_k + bm25_rank)

        base_hit = vector_hit if isinstance(vector_hit, RetrievalHit) else bm25_hit
        if not isinstance(base_hit, RetrievalHit):  # pragma: no cover - every entry has >=1 source
            continue
        bm25_score = bm25_hit.bm25_score if isinstance(bm25_hit, RetrievalHit) else None
        merged = base_hit.model_copy(
            update={
                "vector_rank": vector_rank if isinstance(vector_rank, int) else None,
                "bm25_rank": bm25_rank if isinstance(bm25_rank, int) else None,
                "bm25_score": bm25_score,
            }
        )
        fused.append(
            FusedHit(
                chunk_id=chunk_id,
                rrf_score=score,
                vector_rank=vector_rank if isinstance(vector_rank, int) else None,
                bm25_rank=bm25_rank if isinstance(bm25_rank, int) else None,
                hit=merged,
            )
        )

    fused.sort(key=lambda f: (-f.rrf_score, f.chunk_id))
    for rank, item in enumerate(fused, start=1):
        item.hit = item.hit.model_copy(update={"rrf_rank": rank, "rrf_score": item.rrf_score})
    return fused

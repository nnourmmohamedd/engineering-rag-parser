"""Retrieval-quality metrics: pure functions over retrieved vs. relevant chunk-id lists.

No LLM judge, no paid API — every metric here is a closed-form calculation
over the ground-truth ``relevant_chunk_ids`` supplied in the evaluation
dataset and the ``chunk_id`` list a retrieval call actually returned. Binary
relevance only (a chunk is relevant or it is not — the dataset does not carry
graded relevance), which is why nDCG here uses the binary-relevance form.
"""

from __future__ import annotations

import math

__all__ = [
    "hit_rate_at_k",
    "ndcg_at_k",
    "no_result_correct",
    "precision_at_k",
    "recall_at_k",
    "reciprocal_rank",
]


def hit_rate_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """1.0 if at least one relevant id appears in the top ``k`` retrieved, else 0.0."""
    if not relevant:
        return 0.0
    return 1.0 if set(retrieved[:k]) & relevant else 0.0


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Fraction of all relevant ids that appear in the top ``k`` retrieved."""
    if not relevant:
        return 0.0
    hit_count = len(set(retrieved[:k]) & relevant)
    return hit_count / len(relevant)


def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Fraction of the top ``k`` retrieved that are relevant. Denominator is ``k``, not len(retrieved).

    Note: when fewer than ``k`` results were returned (e.g. filters narrowed
    the collection), this still divides by the requested ``k``, which is the
    conservative reading — it does not inflate precision for a short result
    list. Callers that want "precision over what was actually returned"
    should pass ``k = len(retrieved)`` explicitly.
    """
    if k <= 0:
        return 0.0
    hit_count = len(set(retrieved[:k]) & relevant)
    return hit_count / k


def reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    """1/rank of the first relevant id in ``retrieved`` (1-indexed), or 0.0 if none is present."""
    for i, cid in enumerate(retrieved, start=1):
        if cid in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Binary-relevance nDCG@k: DCG of the actual ranking / DCG of the ideal ranking."""
    if not relevant:
        return 0.0
    top = retrieved[:k]
    dcg = sum((1.0 if cid in relevant else 0.0) / math.log2(i + 1) for i, cid in enumerate(top, start=1))
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


def no_result_correct(top1_similarity: float | None, threshold: float) -> bool | None:
    """Heuristic-only judgment for an ``is_unanswerable`` case.

    Not a ground-truth-verified relevance judgment (no negative-case chunk
    labels exist by construction): returns ``True`` when the top-1
    similarity score falls below ``threshold`` (weak match, consistent with
    "no good answer exists"), ``False`` when it does not, and ``None`` when
    no similarity score was available (e.g. non-cosine collection) to judge.
    """
    if top1_similarity is None:
        return None
    return top1_similarity < threshold

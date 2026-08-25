"""Runs the retrieval benchmark: one query per ground-truth case, scored against relevance labels.

Depends only on :class:`~engineering_rag.services.retriever.retriever.VectorRetriever`
(already constructed and injected by the caller — this module never builds an
embedder or a Chroma client itself) and the pure metric functions in
``.metrics``. Produces one :class:`RetrievalEvaluationResult` per case plus
one aggregate :class:`RetrievalEvaluationSummary`.
"""

from __future__ import annotations

import logging
import statistics
from datetime import datetime, timezone

from engineering_rag.services.retriever.errors import RetrievalError
from engineering_rag.services.retriever.models import (
    RetrievalEvaluationCase,
    RetrievalEvaluationResult,
    RetrievalEvaluationSummary,
    RetrievalRequest,
)
from engineering_rag.services.retriever.retriever import VectorRetriever

from .metrics import (
    hit_rate_at_k,
    ndcg_at_k,
    no_result_correct,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

__all__ = ["evaluate_case", "run_evaluation"]

logger = logging.getLogger(__name__)


def evaluate_case(
    retriever: VectorRetriever,
    case: RetrievalEvaluationCase,
    *,
    k_values: list[int],
    unanswerable_similarity_threshold: float,
) -> RetrievalEvaluationResult:
    """Run one case's query and score the result against its ground-truth labels."""
    max_k = max(k_values)
    warnings: list[str] = []
    retrieved_ids: list[str] = []
    top1_similarity: float | None = None
    latency = 0.0

    try:
        request = RetrievalRequest(query=case.query, top_k=max_k, metadata_filters=case.metadata_filters)
        response = retriever.search(request)
        retrieved_ids = [hit.chunk_id for hit in response.hits]
        latency = response.total_duration_s
        if response.hits:
            top1_similarity = response.hits[0].similarity_score
    except RetrievalError as exc:
        warnings.append(f"retrieval failed for case {case.case_id!r}: {exc}")

    relevant = set(case.relevant_chunk_ids)

    result = RetrievalEvaluationResult(
        case_id=case.case_id,
        query=case.query,
        query_type=case.query_type,
        human_review_status=case.human_review_status,
        retrieved_chunk_ids=retrieved_ids,
        relevant_chunk_ids=case.relevant_chunk_ids,
        latency_s=latency,
        warnings=warnings,
    )

    if case.is_unanswerable:
        result.no_result_correct = no_result_correct(top1_similarity, unanswerable_similarity_threshold)
        return result

    if not relevant:
        result.warnings.append(
            f"case {case.case_id!r} is not marked is_unanswerable but has no relevant_chunk_ids; "
            "hit-rate/recall/precision/MRR/nDCG are all 0.0 by definition, not a retrieval failure."
        )

    result.hit_rate_at_k = {k: hit_rate_at_k(retrieved_ids, relevant, k) for k in k_values}
    result.recall_at_k = {k: recall_at_k(retrieved_ids, relevant, k) for k in k_values}
    result.precision_at_k = {k: precision_at_k(retrieved_ids, relevant, k) for k in k_values}
    result.ndcg_at_k = {k: ndcg_at_k(retrieved_ids, relevant, k) for k in k_values}
    result.reciprocal_rank = reciprocal_rank(retrieved_ids, relevant)
    return result


def run_evaluation(
    retriever: VectorRetriever,
    cases: list[RetrievalEvaluationCase],
    *,
    run_id: str,
    dataset_path: str,
    dataset_hash: str,
    dataset_version: str,
    k_values: list[int],
    unanswerable_similarity_threshold: float,
    collection_name: str,
    collection_count: int,
    distance_metric: str,
    embedding_model: str,
    embedding_revision: str | None,
    reproduction_command: str,
) -> tuple[list[RetrievalEvaluationResult], RetrievalEvaluationSummary]:
    """Evaluate every case and aggregate into a summary. Never calls an LLM or a paid API."""
    results = [
        evaluate_case(
            retriever,
            case,
            k_values=k_values,
            unanswerable_similarity_threshold=unanswerable_similarity_threshold,
        )
        for case in cases
    ]

    positive = [r for r, c in zip(results, cases, strict=True) if not c.is_unanswerable]
    negative = [r for r, c in zip(results, cases, strict=True) if c.is_unanswerable]

    limitations: list[str] = [
        "Metrics use binary relevance from a curated dataset; chunks not labeled relevant are treated "
        "as not relevant, which may undercount true relevance for queries with incomplete judgments.",
        "no_result_accuracy is a heuristic threshold on top-1 similarity, not a ground-truth-verified "
        "judgment of unanswerability — see docs/retrieval/EVALUATION.md.",
    ]
    unreviewed = [c.case_id for c in cases if c.human_review_status == "machine_candidate"]
    if unreviewed:
        limitations.append(
            f"{len(unreviewed)}/{len(cases)} case(s) are machine_candidate (not yet human-reviewed): "
            f"{unreviewed[:10]}{'...' if len(unreviewed) > 10 else ''}"
        )

    latencies = [r.latency_s for r in results]
    failures = [w for r in results for w in r.warnings if "retrieval failed" in w]

    summary = RetrievalEvaluationSummary(
        run_id=run_id,
        generated_at_utc=datetime.now(timezone.utc),
        dataset_path=dataset_path,
        dataset_version=dataset_version,
        dataset_hash=dataset_hash,
        k_values=k_values,
        case_count=len(cases),
        positive_case_count=len(positive),
        negative_case_count=len(negative),
        human_reviewed_count=sum(1 for c in cases if c.human_review_status != "machine_candidate"),
        human_approved_count=sum(1 for c in cases if c.human_review_status == "human_approved"),
        collection_name=collection_name,
        collection_count=collection_count,
        distance_metric=distance_metric,
        embedding_model=embedding_model,
        embedding_revision=embedding_revision,
        hit_rate_at_k=_mean_by_k(positive, "hit_rate_at_k", k_values),
        recall_at_k=_mean_by_k(positive, "recall_at_k", k_values),
        precision_at_k=_mean_by_k(positive, "precision_at_k", k_values),
        mean_reciprocal_rank=round(statistics.fmean([r.reciprocal_rank for r in positive]), 4)
        if positive
        else 0.0,
        ndcg_at_k=_mean_by_k(positive, "ndcg_at_k", k_values),
        no_result_accuracy=_no_result_accuracy(negative),
        latency_p50_s=_percentile(latencies, 0.50),
        latency_p95_s=_percentile(latencies, 0.95),
        latency_mean_s=round(statistics.fmean(latencies), 6) if latencies else 0.0,
        failures=failures,
        warnings=[w for r in results for w in r.warnings if "retrieval failed" not in w],
        limitations=limitations,
        reproduction_command=reproduction_command,
    )
    return results, summary


def _mean_by_k(results: list[RetrievalEvaluationResult], attr: str, k_values: list[int]) -> dict[int, float]:
    if not results:
        return dict.fromkeys(k_values, 0.0)
    out: dict[int, float] = {}
    for k in k_values:
        values = [getattr(r, attr).get(k, 0.0) for r in results]
        out[k] = round(statistics.fmean(values), 4) if values else 0.0
    return out


def _no_result_accuracy(negative: list[RetrievalEvaluationResult]) -> float | None:
    judged = [r.no_result_correct for r in negative if r.no_result_correct is not None]
    if not judged:
        return None
    return round(sum(1 for j in judged if j) / len(judged), 4)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(p * (len(ordered) - 1))))
    return round(ordered[index], 6)

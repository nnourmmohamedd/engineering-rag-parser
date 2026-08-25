"""Evidence-based retrieval evaluation: ground-truth dataset, metrics, and the benchmark runner.

No LLM judge, no paid API — every metric is a closed-form calculation over
curated ``relevant_chunk_ids`` labels. See ``docs/retrieval/EVALUATION.md``.
"""

from __future__ import annotations

from .dataset import dataset_hash, load_evaluation_dataset
from .metrics import hit_rate_at_k, ndcg_at_k, no_result_correct, precision_at_k, recall_at_k, reciprocal_rank
from .runner import evaluate_case, run_evaluation

__all__ = [
    "dataset_hash",
    "evaluate_case",
    "hit_rate_at_k",
    "load_evaluation_dataset",
    "ndcg_at_k",
    "no_result_correct",
    "precision_at_k",
    "recall_at_k",
    "reciprocal_rank",
    "run_evaluation",
]

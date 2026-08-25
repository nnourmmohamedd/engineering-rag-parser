"""Retrieval-domain data contracts: the stable, versioned request/response shapes.

Independent of both ``databases.chroma`` and ``services.embedder`` in the same
way ``services/embedder/models.py`` is independent of ChromaDB — this module
defines what a retrieval hit and response *mean*, not how they were produced.
The pipeline (``pipelines/retrieval_pipeline.py``) is the only place that
constructs these from a live Chroma query result.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "RETRIEVAL_RESPONSE_SCHEMA_VERSION",
    "RetrievalDiagnostics",
    "RetrievalEvaluationCase",
    "RetrievalEvaluationResult",
    "RetrievalEvaluationSummary",
    "RetrievalHit",
    "RetrievalRequest",
    "RetrievalResponse",
    "query_hash",
]

RETRIEVAL_RESPONSE_SCHEMA_VERSION = "1.0.0"


def query_hash(query: str) -> str:
    """Stable, non-reversible fingerprint of a query — safe to log/store instead of raw text."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RetrievalRequest(_Model):
    """One retrieval call's input. Never serialized with a raw embedding vector."""

    query: str
    top_k: int = Field(default=5, gt=0)
    metadata_filters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    collection_name: str | None = Field(
        default=None, description="Override the profile's configured collection. None = use profile default."
    )


class RetrievalHit(_Model):
    """One retrieved chunk with its complete available provenance.

    ``raw_distance`` is Chroma's native distance value, always present.
    ``similarity_score`` is populated only when the collection is verified to
    use cosine distance (``similarity = 1.0 - raw_distance``); it is ``None``
    otherwise, never silently fabricated from an unverified metric.
    """

    rank: int
    chunk_id: str
    retrieval_text: str
    raw_distance: float
    similarity_score: float | None = None

    document_id: str | None = None
    source_filename: str | None = None
    source_sha256: str | None = None
    page_numbers: list[int] = Field(default_factory=list)
    section_title: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    content_type: str | None = None
    chunk_index: int | None = None
    previous_chunk_id: str | None = None
    next_chunk_id: str | None = None
    source_element_refs: list[str] = Field(default_factory=list)
    content_hash: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Full raw stored metadata, unfiltered."
    )


class RetrievalDiagnostics(_Model):
    """Non-fatal observations about one retrieval call — never silently dropped."""

    duplicate_chunk_ids: list[str] = Field(default_factory=list)
    duplicate_content_hashes: list[list[str]] = Field(
        default_factory=list, description="Groups of chunk_ids sharing an identical content_hash."
    )
    tied_distance_groups: list[list[str]] = Field(
        default_factory=list, description="Groups of chunk_ids with an exactly-equal raw_distance."
    )
    warnings: list[str] = Field(default_factory=list)


class RetrievalResponse(_Model):
    """The complete, stable output contract of one retrieval call."""

    schema_version: str = RETRIEVAL_RESPONSE_SCHEMA_VERSION
    query: str
    query_hash: str
    collection_name: str
    requested_top_k: int
    returned_count: int

    embedding_model: str
    embedding_revision: str | None
    embedding_dimension: int
    distance_metric: str

    embedding_duration_s: float
    database_duration_s: float
    total_duration_s: float

    hits: list[RetrievalHit] = Field(default_factory=list)
    diagnostics: RetrievalDiagnostics = Field(default_factory=RetrievalDiagnostics)
    warnings: list[str] = Field(default_factory=list)
    generated_at_utc: datetime | None = None


# --- Evaluation contracts --------------------------------------------------


class RetrievalEvaluationCase(_Model):
    """One ground-truth query/evidence pair in the retrieval benchmark."""

    case_id: str
    query: str
    query_type: Literal[
        "exact_term",
        "acronym",
        "paraphrase",
        "section_level",
        "table",
        "ocr",
        "multi_chunk",
        "negative",
        "metadata_filtered",
    ]
    source_document: str
    relevant_chunk_ids: list[str] = Field(default_factory=list)
    acceptable_page_numbers: list[int] = Field(default_factory=list)
    expected_concepts: list[str] = Field(default_factory=list)
    notes: str = ""
    human_review_status: Literal["machine_candidate", "human_reviewed", "human_approved"] = (
        "machine_candidate"
    )
    metadata_filters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    is_unanswerable: bool = Field(
        default=False, description="True for a deliberately negative case with no correct relevant_chunk_ids."
    )


class RetrievalEvaluationResult(_Model):
    """Per-case evaluation outcome: retrieved hits scored against ground truth, at every K."""

    case_id: str
    query: str
    query_type: str
    human_review_status: str
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    relevant_chunk_ids: list[str] = Field(default_factory=list)
    hit_rate_at_k: dict[int, float] = Field(default_factory=dict)
    recall_at_k: dict[int, float] = Field(default_factory=dict)
    precision_at_k: dict[int, float] = Field(default_factory=dict)
    reciprocal_rank: float = 0.0
    ndcg_at_k: dict[int, float] = Field(default_factory=dict)
    no_result_correct: bool | None = Field(
        default=None,
        description="For is_unanswerable cases only: True if nothing relevant was (wrongly) hit.",
    )
    latency_s: float = 0.0
    warnings: list[str] = Field(default_factory=list)


class RetrievalEvaluationSummary(_Model):
    """Aggregate metrics over one evaluation run."""

    run_id: str
    generated_at_utc: datetime
    dataset_path: str
    dataset_version: str
    dataset_hash: str
    k_values: list[int]
    case_count: int
    positive_case_count: int
    negative_case_count: int
    human_reviewed_count: int
    human_approved_count: int

    collection_name: str
    collection_count: int
    distance_metric: str
    embedding_model: str
    embedding_revision: str | None

    hit_rate_at_k: dict[int, float] = Field(default_factory=dict)
    recall_at_k: dict[int, float] = Field(default_factory=dict)
    precision_at_k: dict[int, float] = Field(default_factory=dict)
    mean_reciprocal_rank: float = 0.0
    ndcg_at_k: dict[int, float] = Field(default_factory=dict)
    no_result_accuracy: float | None = None

    latency_p50_s: float = 0.0
    latency_p95_s: float = 0.0
    latency_mean_s: float = 0.0

    failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    reproduction_command: str = ""

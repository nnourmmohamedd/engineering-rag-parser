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
    "FilterValue",
    "ProvenanceEntry",
    "RetrievalDiagnostics",
    "RetrievalEvaluationCase",
    "RetrievalEvaluationResult",
    "RetrievalEvaluationSummary",
    "RetrievalHit",
    "RetrievalRequest",
    "RetrievalResponse",
    "query_hash",
]

#: One metadata-filter value: a Chroma-legal scalar, or a non-empty list/tuple
#: of them meaning "this field must be one of these" — translated to a native
#: Chroma ``$in`` clause by ``services/retriever/filters.py``. This is how a
#: query is scoped to a set of selected ``document_id`` values at query time.
FilterValue = str | int | float | bool | list[Any] | tuple[Any, ...]

#: 1.1.0: additive-only extension for hybrid retrieval + reranking — every
#: new field defaults to ``None``/empty so a 1.0.0 consumer reading a
#: vector-only response sees identical values for every field it already knew.
RETRIEVAL_RESPONSE_SCHEMA_VERSION = "1.1.0"


def query_hash(query: str) -> str:
    """Stable, non-reversible fingerprint of a query — safe to log/store instead of raw text."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RetrievalRequest(_Model):
    """One retrieval call's input. Never serialized with a raw embedding vector."""

    query: str
    top_k: int = Field(default=5, gt=0)
    metadata_filters: dict[str, FilterValue] = Field(default_factory=dict)
    collection_name: str | None = Field(
        default=None, description="Override the profile's configured collection. None = use profile default."
    )


class ProvenanceEntry(_Model):
    """One page/bbox provenance entry for a chunk, as recorded by the parser/chunker.

    Mirrors ``services.chunker.models.ProvenanceRecord`` minus ``charspan``
    (not needed past retrieval). ``bbox`` is ``(l, t, r, b)`` in PDF points,
    exactly as Docling records it -- never fabricated or estimated here.
    """

    page_no: int
    bbox: tuple[float, float, float, float] | None = None


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
    provenance: list[ProvenanceEntry] = Field(
        default_factory=list, description="Per-page bbox provenance, when the indexer recorded it."
    )
    bbox_reliable: bool = Field(
        default=False,
        description="True only when every provenance bbox denotes this exact chunk's own text -- "
        "False for a chunk produced by recursive splitting or merging, where a bbox (if present) "
        "covers the whole original element, not this specific sub-passage. Never set True by "
        "estimation; only when the chunker recorded it as such.",
    )

    # --- Hybrid retrieval / reranking evidence (all None in vector-only mode) ---
    final_rank: int | None = Field(
        default=None,
        description="Rank in the final returned list, after every enabled stage. Mirrors `rank`.",
    )
    vector_rank: int | None = Field(default=None, description="This chunk's rank in the vector-only ranking.")
    bm25_rank: int | None = Field(default=None, description="This chunk's rank in the BM25-only ranking.")
    bm25_score: float | None = Field(
        default=None, description="Raw BM25 score, not comparable to vector distance."
    )
    rrf_rank: int | None = Field(default=None, description="This chunk's rank after Reciprocal Rank Fusion.")
    rrf_score: float | None = Field(default=None, description="This chunk's Reciprocal Rank Fusion score.")
    reranker_rank: int | None = Field(
        default=None, description="This chunk's rank after cross-encoder reranking."
    )
    reranker_score: float | None = Field(
        default=None,
        description="Raw cross-encoder logit/sigmoid output. NOT a calibrated probability of relevance.",
    )

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

    # --- Hybrid retrieval / reranking run metadata (defaults preserve vector-only responses) ---
    retrieval_mode: Literal["vector", "hybrid", "hybrid-rerank", "vector-rerank"] = "vector"
    vector_enabled: bool = True
    bm25_enabled: bool = False
    reranker_enabled: bool = False
    candidate_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Candidate count after each executed stage, e.g. "
        "{'vector': 30, 'bm25': 30, 'fused': 45, 'reranked': 5}.",
    )
    stage_latencies_s: dict[str, float] = Field(
        default_factory=dict, description="Wall-clock duration of each executed stage."
    )
    bm25_index_path: str | None = None
    bm25_corpus_fingerprint: str | None = None
    reranker_model: str | None = None
    reranker_model_revision: str | None = None


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
    metadata_filters: dict[str, FilterValue] = Field(default_factory=dict)
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
    retrieval_mode: str = "vector"
    bm25_enabled: bool = False
    reranker_enabled: bool = False

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

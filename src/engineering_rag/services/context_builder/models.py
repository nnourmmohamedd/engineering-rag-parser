"""Context-building domain contracts: the stable, versioned output of one context-build call.

Independent of ``clients/ollama`` and ``chromadb`` -- these models describe
what was selected and why, never how generation will use it. Only
:mod:`engineering_rag.services.context_builder.builder` constructs a
:class:`ContextPackage`.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CONTEXT_SCHEMA_VERSION",
    "ContextPackage",
    "ExcludedCandidate",
    "NeighborChunk",
    "SelectedSource",
    "query_hash",
]

#: Bumped whenever context-selection semantics change in a way that would
#: alter the selected sources or their fields for identical input+config.
CONTEXT_SCHEMA_VERSION = "1.0.0"

ExclusionReason = Literal[
    "malformed_provenance",
    "duplicate_chunk_id",
    "duplicate_content_hash",
    "per_document_limit",
    "per_section_limit",
    "token_budget_exceeded",
    "max_sources_reached",
    "chunk_exceeds_budget_alone",
]

SelectionReason = Literal["directly_retrieved", "neighbor_expansion"]


def query_hash(query: str) -> str:
    """Stable, non-reversible fingerprint of a query -- safe to log/store instead of raw text."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NeighborChunk(_Model):
    """One chunk fetched by an injected :class:`~.neighbor_provider.NeighborProvider`.

    Deliberately independent of ``chromadb`` -- a concrete provider (e.g. a
    Chroma-backed one) translates its own native record into this shape;
    the context builder never sees a Chroma object.
    """

    chunk_id: str
    document_id: str | None = None
    retrieval_text: str
    source_filename: str | None = None
    source_sha256: str | None = None
    page_numbers: list[int] = Field(default_factory=list)
    section_title: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    content_type: str | None = None
    content_hash: str | None = None
    chunk_index: int | None = None
    previous_chunk_id: str | None = None
    next_chunk_id: str | None = None


class SelectedSource(_Model):
    """One chunk selected into the final context, with complete provenance and selection evidence."""

    citation_id: str = Field(
        description="Answer-local citation ID, e.g. 'S1'. Assigned only after selection."
    )
    chunk_id: str
    chunk_index: int | None = None
    document_id: str | None = None
    retrieval_text: str
    source_filename: str | None = None
    page_numbers: list[int] = Field(default_factory=list)
    section_title: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    content_type: str | None = None
    source_sha256: str | None = None
    content_hash: str | None = None
    previous_chunk_id: str | None = None
    next_chunk_id: str | None = None

    # --- retrieval evidence (whatever the active retrieval mode populated) ---
    vector_rank: int | None = None
    bm25_rank: int | None = None
    rrf_rank: int | None = None
    reranker_rank: int | None = None
    retrieval_rank: int | None = Field(default=None, description="Final rank returned by the retrieval call.")
    similarity_score: float | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None
    reranker_score: float | None = None

    is_neighbor: bool = Field(
        default=False, description="False for a directly retrieved hit, True for a neighbor."
    )
    selection_order: int = Field(
        description="1-based order this source was selected in (before citation IDs)."
    )
    token_count: int = Field(description="Token count of retrieval_text alone, per the active TokenCounter.")
    selection_reason: SelectionReason = "directly_retrieved"


class ExcludedCandidate(_Model):
    """One candidate that was NOT selected, with a deterministic, honest reason."""

    chunk_id: str
    document_id: str | None = None
    source_filename: str | None = None
    reason: ExclusionReason
    detail: str = ""


class ContextPackage(_Model):
    """The complete, stable output contract of one context-build call."""

    context_schema_version: str = CONTEXT_SCHEMA_VERSION
    query: str
    query_hash: str
    retrieval_mode: str

    selected_sources: list[SelectedSource] = Field(default_factory=list)
    excluded_candidates: list[ExcludedCandidate] = Field(default_factory=list)

    total_candidates_received: int = 0
    total_sources_selected: int = 0

    context_token_count: int = Field(description="Token count of the fully rendered context_text.")
    token_budget: int = Field(description="context_builder.max_context_tokens for this build.")
    reserved_output_tokens: int = Field(
        description="ollama.max_output_tokens reserved out of the model's window."
    )
    prompt_overhead_tokens: int = Field(
        description="context_builder.reserved_system_tokens + safety_margin_tokens for this build."
    )

    context_text: str = Field(description="Fully rendered, delimited, sanitized evidence blocks.")

    source_hashes: list[str] = Field(
        default_factory=list,
        description="Sorted, de-duplicated source_sha256 values across selected_sources.",
    )
    tokenizer_description: str = ""

    warnings: list[str] = Field(default_factory=list)
    selection_duration_s: float = 0.0
    generated_at_utc: datetime | None = None

"""Typed data contracts for the persistent BM25 lexical index."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "BM25_INDEX_SCHEMA_VERSION",
    "BM25CorpusRecord",
    "BM25Manifest",
    "BM25RawHit",
    "BM25ValidationCheck",
    "BM25ValidationReport",
]

#: Bumped whenever the on-disk index layout or manifest contract changes.
BM25_INDEX_SCHEMA_VERSION = "1.0.0"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BM25CorpusRecord(_Model):
    """One chunk as read from the live Chroma collection, kept alongside the BM25 index.

    This is the exact same provenance a vector hit carries — the BM25 index
    never invents or re-derives a chunk, it only re-ranks the identical set
    ``VectorRetriever`` searches.
    """

    chunk_id: str
    retrieval_text: str
    document_id: str | None = None
    source_filename: str | None = None
    source_sha256: str | None = None
    page_numbers: list[int] = Field(default_factory=list)
    heading_path: list[str] = Field(default_factory=list)
    section_title: str | None = None
    content_type: str | None = None
    content_hash: str | None = None
    chunk_schema_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BM25RawHit(_Model):
    """One BM25 search result before it is merged into the shared retrieval contract."""

    bm25_rank: int
    bm25_score: float
    record: BM25CorpusRecord


class BM25Manifest(_Model):
    """Everything needed to verify a persistent BM25 index without loading it.

    Written atomically alongside the index itself
    (``index.build_bm25_index``); read by
    ``services/retriever/corpus_compat.py`` to gate hybrid search against a
    stale or mismatched index.
    """

    schema_version: str = BM25_INDEX_SCHEMA_VERSION
    generated_at_utc: datetime
    collection_name: str
    chroma_persistence_path: str

    corpus_count: int
    corpus_fingerprint: str = Field(
        description="Deterministic SHA-256 over the sorted (chunk_id, content_hash) pairs of every "
        "indexed record — changes if and only if the indexed chunk set changes."
    )
    chunk_ids: list[str]
    document_ids: list[str] = Field(default_factory=list)
    source_filenames: list[str] = Field(default_factory=list)
    content_hashes: dict[str, str] = Field(
        default_factory=dict, description="chunk_id -> content_hash, for exact per-record comparison."
    )
    chunk_schema_versions: list[str] = Field(default_factory=list)

    bm25_library: str
    bm25_library_version: str
    tokenizer_version: str
    method: str
    k1: float
    b: float

    index_creation_duration_s: float = 0.0
    warnings: list[str] = Field(default_factory=list)


class BM25ValidationCheck(_Model):
    check_id: str
    passed: bool
    summary: str


class BM25ValidationReport(_Model):
    status: str
    checks: list[BM25ValidationCheck] = Field(default_factory=list)

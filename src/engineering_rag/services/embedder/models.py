"""Embedding-service domain models: typed request/response records.

Deliberately free of any ChromaDB or numpy-specific storage concern — this is
the stable, library-independent contract the pipeline and the Chroma adapter
both consume via plain ``list[float]`` vectors.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "EmbeddingBatchStats",
    "EmbeddingRecord",
    "ModelInfo",
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelInfo(_Model):
    """Reported identity of the loaded embedding model — recorded in every index manifest."""

    model_name: str
    resolved_revision: str | None = None
    dimension: int
    max_seq_length: int
    device: str
    tokenizer_name: str
    normalize_embeddings: bool


class EmbeddingRecord(BaseModel):
    """One embedded passage, in caller-supplied order.

    Not frozen/``extra=forbid``: this is an internal in-memory transfer
    object between the embedder and the pipeline, not a serialized artifact.
    """

    chunk_id: str
    vector: list[float] = Field(repr=False)  # never repr a full vector in logs/tracebacks

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"EmbeddingRecord(chunk_id={self.chunk_id!r}, dim={len(self.vector)})"


class EmbeddingBatchStats(_Model):
    """Throughput/timing summary for one ``embed_passages`` call — never full text or vectors."""

    input_count: int
    batch_size: int
    duration_s: float
    vectors_per_second: float

"""Shared fixtures for retriever unit tests: a small, real, ephemeral Chroma collection."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from engineering_rag.databases.chroma.client import get_client
from engineering_rag.databases.chroma.metadata import chroma_safe_metadata
from engineering_rag.services.embedder.errors import EmptyQueryError
from engineering_rag.services.embedder.interface import EmbeddingService
from engineering_rag.services.embedder.models import EmbeddingBatchStats, EmbeddingRecord, ModelInfo


class FixedVectorEmbedder(EmbeddingService):
    """A test double that returns a caller-specified, exact vector for every query.

    Records every query text it was asked to embed (with any prefix already
    applied by the caller) so a test can assert the query prefix was applied
    exactly once.
    """

    def __init__(self, vector: list[float], *, query_prefix: str = "PREFIX: ") -> None:
        self.vector = vector
        self.query_prefix = query_prefix
        self.embedded_queries: list[str] = []

    def model_info(self) -> ModelInfo:
        return ModelInfo(
            model_name="fixed-test-embedder",
            resolved_revision="test",
            dimension=len(self.vector),
            max_seq_length=512,
            device="cpu",
            tokenizer_name="fixed-test-embedder",
            normalize_embeddings=True,
        )

    def embed_passages(
        self, chunk_ids: list[str], texts: list[str]
    ) -> tuple[list[EmbeddingRecord], EmbeddingBatchStats]:
        raise NotImplementedError("not needed for retrieval tests")

    def embed_query(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise EmptyQueryError("Query text must not be empty or whitespace-only")
        self.embedded_queries.append(self.query_prefix + text)
        return list(self.vector)

    def health_check(self) -> None:
        self.embed_query("health check")


def _unit_vector(hot_index: int, dim: int = 8) -> list[float]:
    v = [0.01] * dim
    v[hot_index % dim] = 1.0
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


@pytest.fixture
def small_collection(tmp_path: Path) -> Any:
    """A real, ephemeral cosine-space Chroma collection with 4 hand-built records."""
    client = get_client(tmp_path / "chroma")
    collection = client.create_collection(
        name="retriever-test-collection",
        metadata={
            "hnsw:space": "cosine",
            "distance_metric": "cosine",
            "model_name": "fake",
            "embedding_dimension": 8,
        },
        embedding_function=None,
    )
    records = [
        ("chunk_a", "First chunk about control systems.", 0, "a.pdf", "text", [1], "hash_a"),
        ("chunk_b", "Second chunk about wiring diagrams.", 1, "a.pdf", "text", [2], "hash_b"),
        ("chunk_c", "Third chunk, a table of instrument tags.", 2, "b.pdf", "table", [3], "hash_c"),
        ("chunk_d", "Fourth chunk duplicating chunk_a's content.", 3, "a.pdf", "text", [4], "hash_a"),
    ]
    ids = [r[0] for r in records]
    documents = [r[1] for r in records]
    embeddings = [_unit_vector(i) for i in range(len(records))]
    metadatas = [
        chroma_safe_metadata(
            {
                "chunk_index": r[2],
                "source_filename": r[3],
                "content_type": r[4],
                "page_numbers": r[5],
                "heading_path": ["Root", "Sub"],
                "content_hash": r[6],
                "document_id": "doc1",
                "section_title": "A Section",
                "previous_chunk_id": None,
                "next_chunk_id": None,
                "source_element_refs": ["#/texts/0"],
            }
        )
        for r in records
    ]
    collection.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
    return collection


@pytest.fixture
def chunk_a_vector() -> list[float]:
    return _unit_vector(0)


@pytest.fixture
def empty_collection(tmp_path: Path) -> Any:
    client = get_client(tmp_path / "chroma_empty")
    return client.create_collection(
        name="empty-collection",
        metadata={"hnsw:space": "cosine", "distance_metric": "cosine"},
        embedding_function=None,
    )

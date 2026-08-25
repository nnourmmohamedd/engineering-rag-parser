"""A deterministic, network-free fake implementing :class:`EmbeddingService`.

Used everywhere a test needs an embedder but must never download the real
BGE model: unit tests, Chroma integration tests, and the indexing pipeline's
own unit tests (injected via ``IndexingRequest.embedder``). Vectors are
seeded from a SHA-256 hash of the input text, so the same text always
produces the same 768-d, L2-normalized vector, and different texts (almost
certainly) produce different vectors — good enough to exercise every code
path (ordering, storage, round-trip, self-retrieval) without any of the
real model's semantic properties.
"""

from __future__ import annotations

import hashlib
import math
import time

from engineering_rag.services.embedder.errors import EmptyQueryError
from engineering_rag.services.embedder.interface import EmbeddingService
from engineering_rag.services.embedder.models import EmbeddingBatchStats, EmbeddingRecord, ModelInfo
from engineering_rag.services.embedder.validation import validate_vector

__all__ = ["FakeEmbeddingService"]

_DIMENSION = 768


def _deterministic_vector(text: str, dimension: int = _DIMENSION) -> list[float]:
    """A reproducible, normalized pseudo-embedding derived from ``text``'s hash."""
    raw: list[float] = []
    counter = 0
    while len(raw) < dimension:
        digest = hashlib.sha256(f"{text}|{counter}".encode()).digest()
        raw.extend(b / 127.5 - 1.0 for b in digest)
        counter += 1
    values = raw[:dimension]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


class FakeEmbeddingService(EmbeddingService):
    """Deterministic, CPU-only, no-network embedder matching the real interface."""

    def __init__(
        self,
        *,
        query_prefix: str = "Represent this sentence for searching relevant passages: ",
        dimension: int = _DIMENSION,
        model_name: str = "fake-embedder-for-tests",
    ) -> None:
        self._query_prefix = query_prefix
        self._dimension = dimension
        self._model_name = model_name

    def model_info(self) -> ModelInfo:
        return ModelInfo(
            model_name=self._model_name,
            resolved_revision="fake",
            dimension=self._dimension,
            max_seq_length=512,
            device="cpu",
            tokenizer_name=self._model_name,
            normalize_embeddings=True,
        )

    def embed_passages(
        self, chunk_ids: list[str], texts: list[str]
    ) -> tuple[list[EmbeddingRecord], EmbeddingBatchStats]:
        if len(chunk_ids) != len(texts):
            raise ValueError(f"chunk_ids ({len(chunk_ids)}) and texts ({len(texts)}) length mismatch")
        started = time.perf_counter()
        records = []
        for cid, text in zip(chunk_ids, texts, strict=True):
            vector = _deterministic_vector(text, self._dimension)
            validate_vector(vector, chunk_id=cid, expected_dimension=self._dimension, normalize_expected=True)
            records.append(EmbeddingRecord(chunk_id=cid, vector=vector))
        duration = max(time.perf_counter() - started, 1e-9)
        stats = EmbeddingBatchStats(
            input_count=len(texts),
            batch_size=len(texts),
            duration_s=round(duration, 6),
            vectors_per_second=round(len(texts) / duration, 2),
        )
        return records, stats

    def embed_query(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise EmptyQueryError("Query text must not be empty or whitespace-only")
        vector = _deterministic_vector(self._query_prefix + text, self._dimension)
        validate_vector(vector, chunk_id=None, expected_dimension=self._dimension, normalize_expected=True)
        return vector

    def health_check(self) -> None:
        self.embed_query("health check smoke test")

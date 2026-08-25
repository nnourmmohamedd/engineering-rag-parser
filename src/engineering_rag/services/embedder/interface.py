"""Typed interface every embedding-service implementation must satisfy.

Independent of ChromaDB: nothing under ``services/embedder/`` imports
``chromadb``. Implementations return plain ``list[float]`` vectors; the
Chroma adapter (``databases/chroma/``) is the only place a vector is handed
to a specific vector store.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import EmbeddingBatchStats, EmbeddingRecord, ModelInfo

__all__ = ["EmbeddingService"]


class EmbeddingService(ABC):
    """Abstract embedding backend: passage embedding, query embedding, health/model info."""

    @abstractmethod
    def model_info(self) -> ModelInfo:
        """Return the resolved identity of the loaded model (name, revision, dim, device, ...)."""

    @abstractmethod
    def embed_passages(
        self, chunk_ids: list[str], texts: list[str]
    ) -> tuple[list[EmbeddingRecord], EmbeddingBatchStats]:
        """Embed a batch of passages (no instruction prefix), preserving input order exactly.

        Args:
            chunk_ids: stable identifiers, one per text, same order as ``texts``.
            texts: the passage text to embed (already extracted from the
                configured ``document_field``, e.g. ``retrieval_text``).

        Returns:
            ``(records, stats)`` where ``records[i].chunk_id == chunk_ids[i]``
            and ``records[i].vector`` is the normalized embedding for ``texts[i]``.

        Raises:
            VectorValidationError: if any produced vector fails validation.
        """

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed one query: prepend the query prefix, normalize, return a single vector.

        Raises:
            EmptyQueryError: if ``text`` is empty or whitespace-only.
            VectorValidationError: if the produced vector fails validation.
        """

    @abstractmethod
    def health_check(self) -> None:
        """Validate the model is loaded and produces well-formed vectors, or raise.

        Raises:
            ModelLoadError: if the model failed to load.
            VectorValidationError: if a smoke-test embedding is malformed.
        """

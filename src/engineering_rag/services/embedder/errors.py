"""Typed exceptions raised by the embedding service.

Kept separate from :mod:`.interface` so callers (pipeline, tests, CLI) can
import just the exception vocabulary without pulling in the ABC.
"""

from __future__ import annotations

__all__ = [
    "EmbeddingError",
    "EmptyQueryError",
    "ModelLoadError",
    "VectorValidationError",
]


class EmbeddingError(Exception):
    """Base class for every embedding-service failure."""


class EmptyQueryError(EmbeddingError):
    """Raised when a query is empty or whitespace-only."""


class ModelLoadError(EmbeddingError):
    """Raised when the underlying model/tokenizer cannot be loaded (network, cache, offline)."""


class VectorValidationError(EmbeddingError):
    """Raised when a produced embedding vector fails validation (dimension, NaN/Inf, zero, norm)."""

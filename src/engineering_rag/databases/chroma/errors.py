"""Typed exceptions raised by the Chroma adapter."""

from __future__ import annotations

__all__ = [
    "ChromaAdapterError",
    "CollectionMismatchError",
    "DuplicateIdConflictError",
    "InvalidCollectionNameError",
]


class ChromaAdapterError(Exception):
    """Base class for every Chroma-adapter failure."""


class InvalidCollectionNameError(ChromaAdapterError):
    """Raised when a configured collection name fails Chroma's own naming constraints."""


class CollectionMismatchError(ChromaAdapterError):
    """Raised when an existing collection's stored metadata declares a different
    model/dimension/metric/schema than the current run's configuration."""


class DuplicateIdConflictError(ChromaAdapterError):
    """Raised when a rerun would write an id that already exists with a *different* content hash."""

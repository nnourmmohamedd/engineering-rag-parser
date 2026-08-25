"""Typed exceptions raised by the retrieval service."""

from __future__ import annotations

__all__ = [
    "CollectionNotFoundError",
    "EmptyCollectionError",
    "InvalidFilterError",
    "MalformedChromaResponseError",
    "RetrievalError",
]


class RetrievalError(Exception):
    """Base class for every retrieval-service failure."""


class CollectionNotFoundError(RetrievalError):
    """Raised when the configured Chroma database path or collection does not exist.

    Retrieval never creates a collection as a side effect of searching it.
    """


class EmptyCollectionError(RetrievalError):
    """Raised when the target collection exists but contains zero records."""


class InvalidFilterError(RetrievalError):
    """Raised when a caller-supplied metadata filter uses an unsupported field or type."""


class MalformedChromaResponseError(RetrievalError):
    """Raised when a Chroma query response has mismatched or missing array lengths."""

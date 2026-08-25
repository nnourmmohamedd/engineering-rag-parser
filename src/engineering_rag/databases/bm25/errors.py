"""Typed exceptions raised by the BM25 lexical index adapter."""

from __future__ import annotations

__all__ = [
    "BM25Error",
    "BM25IndexNotFoundError",
    "CorpusValidationError",
]


class BM25Error(Exception):
    """Base class for every BM25 index failure."""


class BM25IndexNotFoundError(BM25Error):
    """Raised when a persistent BM25 index is expected but not found on disk."""


class CorpusValidationError(BM25Error):
    """Raised when the source corpus fails a build-time validation gate.

    Covers duplicate chunk ids, missing/empty ``retrieval_text``, and other
    malformed records that must never be silently indexed.
    """

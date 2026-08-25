"""Typed exceptions raised by the reranker service."""

from __future__ import annotations

__all__ = ["RerankerError", "RerankerModelLoadError"]


class RerankerError(Exception):
    """Base class for every reranker-service failure."""


class RerankerModelLoadError(RerankerError):
    """Raised when the cross-encoder model fails to load."""

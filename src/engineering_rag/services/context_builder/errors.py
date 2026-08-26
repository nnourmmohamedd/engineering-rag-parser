"""Typed exceptions raised by the context-builder service."""

from __future__ import annotations

__all__ = ["ContextBuilderError", "TokenizerLoadError"]


class ContextBuilderError(Exception):
    """Base class for every context-builder failure."""


class TokenizerLoadError(ContextBuilderError):
    """Raised when the configured production tokenizer fails to load."""

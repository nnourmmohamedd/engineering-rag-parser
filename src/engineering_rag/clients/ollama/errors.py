"""Typed exceptions raised by the Ollama client."""

from __future__ import annotations

__all__ = [
    "OllamaConnectionError",
    "OllamaDigestMismatchError",
    "OllamaError",
    "OllamaModelNotFoundError",
    "OllamaResponseError",
    "OllamaTimeoutError",
]


class OllamaError(Exception):
    """Base class for every Ollama-client failure."""


class OllamaConnectionError(OllamaError):
    """Raised when the Ollama server cannot be reached (connection refused/DNS/etc.)."""


class OllamaTimeoutError(OllamaError):
    """Raised when a request to Ollama exceeds its configured timeout."""


class OllamaModelNotFoundError(OllamaError):
    """Raised when the configured model is not installed locally on the Ollama server."""


class OllamaDigestMismatchError(OllamaError):
    """Raised when the installed model's digest does not match the configured ``expected_digest``."""


class OllamaResponseError(OllamaError):
    """Raised when Ollama returns a non-2xx status or a response that cannot be parsed."""

"""Local Ollama HTTP client: transport only, no retrieval/prompting/grounding logic.

Talks to the native Ollama HTTP API (``GET /api/version``, ``GET /api/tags``,
``POST /api/chat``) over ``httpx``. ``base_url`` is restricted to a localhost
address by configuration validation -- this project never calls a remote or
cloud Ollama endpoint. See ``README.md``.
"""

from __future__ import annotations

from engineering_rag import __version__

__all__ = [
    "OLLAMA_CLIENT_VERSION",
    "LLMClient",
    "OllamaConfig",
    "OllamaConnectionError",
    "OllamaDigestMismatchError",
    "OllamaError",
    "OllamaGenerationMetrics",
    "OllamaHTTPClient",
    "OllamaModelInfo",
    "OllamaModelNotFoundError",
    "OllamaResponseError",
    "OllamaTimeoutError",
    "OllamaVersionInfo",
    "StructuredChatResult",
]

OLLAMA_CLIENT_VERSION = __version__

from .config import OllamaConfig  # noqa: E402
from .errors import (  # noqa: E402
    OllamaConnectionError,
    OllamaDigestMismatchError,
    OllamaError,
    OllamaModelNotFoundError,
    OllamaResponseError,
    OllamaTimeoutError,
)
from .http_client import OllamaHTTPClient  # noqa: E402
from .interface import LLMClient  # noqa: E402
from .models import (  # noqa: E402
    OllamaGenerationMetrics,
    OllamaModelInfo,
    OllamaVersionInfo,
    StructuredChatResult,
)

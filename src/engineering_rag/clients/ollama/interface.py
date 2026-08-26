"""Typed interface every LLM client implementation must satisfy.

``services/answerer`` depends on this interface only, never on
:class:`~.http_client.OllamaHTTPClient` directly -- fast tests inject a fake
implementation with no network access at all.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .models import OllamaModelInfo, OllamaVersionInfo, StructuredChatResult

__all__ = ["LLMClient"]


class LLMClient(ABC):
    """A local, non-streaming, structured-output chat generation client."""

    @abstractmethod
    def health_check(self) -> bool:
        """Return True if the server responds, without raising on connection failure."""

    @abstractmethod
    def version(self) -> OllamaVersionInfo:
        """Raises OllamaConnectionError/OllamaTimeoutError/OllamaResponseError on failure."""

    @abstractmethod
    def list_models(self) -> list[OllamaModelInfo]:
        """Every model currently installed on the server."""

    @abstractmethod
    def model_info(self, model: str) -> OllamaModelInfo:
        """Raises OllamaModelNotFoundError if ``model`` is not installed locally."""

    @abstractmethod
    def generate_structured(
        self, *, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> StructuredChatResult:
        """One non-streaming chat call constrained to ``json_schema``. Thinking is always disabled.

        Raises:
            OllamaConnectionError: the server could not be reached.
            OllamaTimeoutError: the request exceeded its configured timeout.
            OllamaModelNotFoundError: the configured model is not installed.
            OllamaResponseError: a non-2xx status or an unparseable response.
        """

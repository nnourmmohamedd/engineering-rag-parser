"""Production Ollama client: the native Ollama HTTP API over ``httpx``.

``httpx`` is already an installed transitive dependency (via ``chromadb``),
so this client adds no new dependency. No network request is made at module
import time or at :class:`OllamaHTTPClient` construction time -- the
``httpx.Client`` is only configured, not connected, until the first call.

Transport only: no retrieval, no prompting, no grounding logic lives here.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .config import OllamaConfig
from .errors import (
    OllamaConnectionError,
    OllamaError,
    OllamaModelNotFoundError,
    OllamaResponseError,
    OllamaTimeoutError,
)
from .interface import LLMClient
from .models import OllamaGenerationMetrics, OllamaModelInfo, OllamaVersionInfo, StructuredChatResult

__all__ = ["OllamaHTTPClient"]

logger = logging.getLogger(__name__)


class OllamaHTTPClient(LLMClient):
    """Talks to a local Ollama server. Retries only safe, transient connection errors."""

    def __init__(self, config: OllamaConfig) -> None:
        self._config = config
        timeout = httpx.Timeout(
            connect=config.connect_timeout_seconds,
            read=config.read_timeout_seconds,
            write=config.connect_timeout_seconds,
            pool=config.connect_timeout_seconds,
        )
        self._client = httpx.Client(base_url=config.base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OllamaHTTPClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None) -> httpx.Response:
        """Bounded retry on connection failures only. Never retries a timed-out or bad-status response."""
        attempts = self._config.max_retries + 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return self._client.request(method, path, json=json_body)
            except httpx.TimeoutException as exc:
                raise OllamaTimeoutError(
                    f"Ollama request {method} {path} timed out "
                    f"(connect={self._config.connect_timeout_seconds}s, read={self._config.read_timeout_seconds}s): {exc}"
                ) from exc
            except httpx.TransportError as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                logger.warning(
                    "Ollama %s %s connection error (attempt %d/%d): %s", method, path, attempt, attempts, exc
                )
                continue
        raise OllamaConnectionError(
            f"Could not connect to Ollama at {self._config.base_url} after {attempts} attempt(s): {last_error}"
        ) from last_error

    def health_check(self) -> bool:
        try:
            response = self._request("GET", "/api/version")
        except OllamaError:
            return False
        return response.status_code == 200

    def version(self) -> OllamaVersionInfo:
        response = self._request("GET", "/api/version")
        if response.status_code != 200:
            raise OllamaResponseError(f"Unexpected status {response.status_code} from GET /api/version")
        data = _parse_json(response, "/api/version")
        return OllamaVersionInfo(version=str(data.get("version", "")))

    def list_models(self) -> list[OllamaModelInfo]:
        response = self._request("GET", "/api/tags")
        if response.status_code != 200:
            raise OllamaResponseError(f"Unexpected status {response.status_code} from GET /api/tags")
        data = _parse_json(response, "/api/tags")
        models = []
        for entry in data.get("models", []) or []:
            details = entry.get("details") or {}
            models.append(
                OllamaModelInfo(
                    name=str(entry.get("model") or entry.get("name") or ""),
                    digest=str(entry.get("digest", "")),
                    size_bytes=int(entry.get("size", 0) or 0),
                    parameter_size=str(details.get("parameter_size", "")),
                    quantization_level=str(details.get("quantization_level", "")),
                    family=str(details.get("family", "")),
                    modified_at=str(entry.get("modified_at", "")),
                )
            )
        return models

    def model_info(self, model: str) -> OllamaModelInfo:
        for info in self.list_models():
            if info.name == model:
                return info
        raise OllamaModelNotFoundError(f"Model {model!r} is not installed locally. Run: ollama pull {model}")

    def generate_structured(
        self, *, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> StructuredChatResult:
        config = self._config
        options: dict[str, Any] = {
            "temperature": config.temperature,
            "num_ctx": config.context_window_tokens,
            "num_predict": config.max_output_tokens,
        }
        if config.seed is not None:
            options["seed"] = config.seed

        payload = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "think": config.think,
            "format": json_schema,
            "keep_alive": config.keep_alive,
            "options": options,
        }

        started = time.perf_counter()
        response = self._request("POST", "/api/chat", json_body=payload)
        wall_clock_s = time.perf_counter() - started

        if response.status_code == 404:
            raise OllamaModelNotFoundError(
                f"Model {config.model!r} was not found on the Ollama server. Run: ollama pull {config.model}"
            )
        if response.status_code != 200:
            raise OllamaResponseError(
                f"Ollama POST /api/chat returned status {response.status_code}: {response.text[:500]}"
            )
        data = _parse_json(response, "/api/chat")

        message = data.get("message") or {}
        metrics = OllamaGenerationMetrics(
            prompt_eval_count=int(data.get("prompt_eval_count", 0) or 0),
            eval_count=int(data.get("eval_count", 0) or 0),
            load_duration_ns=int(data.get("load_duration", 0) or 0),
            prompt_eval_duration_ns=int(data.get("prompt_eval_duration", 0) or 0),
            eval_duration_ns=int(data.get("eval_duration", 0) or 0),
            total_duration_ns=int(data.get("total_duration", 0) or 0),
            wall_clock_s=round(wall_clock_s, 4),
        )
        return StructuredChatResult(
            raw_content=str(message.get("content", "")),
            metrics=metrics,
            model=str(data.get("model", config.model)),
            done=bool(data.get("done", False)),
            done_reason=data.get("done_reason"),
        )


def _parse_json(response: httpx.Response, path: str) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise OllamaResponseError(
            f"Ollama {path} returned a non-JSON response: {response.text[:200]}"
        ) from exc
    if not isinstance(data, dict):
        raise OllamaResponseError(f"Ollama {path} returned a JSON value that is not an object")
    return data

"""Validated, hashable configuration for the local Ollama client.

``think`` is hard-validated to ``False`` -- this project's production path
never requests or stores hidden reasoning (see
``docs/answering/SECURITY_AND_GROUNDING.md``). ``base_url`` is restricted to
a localhost address by default validation, matching this milestone's
"local-only, no cloud inference" requirement -- there is no CLI flag that
lets a caller point this at an arbitrary remote URL.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = ["OllamaConfig"]

_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class OllamaConfig(_Frozen):
    """Local Ollama server connection + generation parameters."""

    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3:8b"
    expected_digest: str | None = Field(
        default=None,
        description="Recorded model digest from `ollama list` / GET /api/tags. Validated at startup.",
    )
    strict_digest: bool = Field(
        default=True, description="Refuse to run if the installed model's digest != expected_digest."
    )

    think: bool = False
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    seed: int | None = 42
    context_window_tokens: int = Field(
        default=8192, gt=0, description="Explicit `num_ctx`; never Ollama's default."
    )
    max_output_tokens: int = Field(default=1024, gt=0, description="Explicit `num_predict`.")
    keep_alive: str = "10m"

    connect_timeout_seconds: float = Field(default=5.0, gt=0)
    read_timeout_seconds: float = Field(default=180.0, gt=0)
    max_retries: int = Field(
        default=1,
        ge=0,
        le=5,
        description="Bounded retries for transient connection errors only. Never for "
        "schema/validation errors, and never for a read timeout on a generation that was already in flight.",
    )

    def effective_dict(self) -> dict[str, Any]:
        return json.loads(self.model_dump_json())

    def config_hash(self) -> str:
        payload = json.dumps(self.effective_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def _validate(self) -> OllamaConfig:
        if self.think:
            raise ValueError(
                "ollama.think must be false in production: no hidden reasoning is requested or stored"
            )
        host = urlparse(self.base_url).hostname
        if host not in _ALLOWED_HOSTS:
            raise ValueError(
                f"ollama.base_url must point at a local Ollama server (host in {sorted(_ALLOWED_HOSTS)}), "
                f"got host={host!r}. This project never calls a remote/cloud Ollama endpoint."
            )
        return self

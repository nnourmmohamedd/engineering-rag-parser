"""Typed shapes for Ollama HTTP responses. No network calls; no business logic."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "OllamaGenerationMetrics",
    "OllamaModelInfo",
    "OllamaVersionInfo",
    "StructuredChatResult",
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OllamaVersionInfo(_Model):
    """Result of ``GET /api/version``."""

    version: str


class OllamaModelInfo(_Model):
    """One entry from ``GET /api/tags``, describing a locally-installed model."""

    name: str
    digest: str
    size_bytes: int
    parameter_size: str = ""
    quantization_level: str = ""
    family: str = ""
    modified_at: str = ""


class OllamaGenerationMetrics(_Model):
    """Timing/count evidence returned alongside one ``POST /api/chat`` response.

    Ollama reports durations in nanoseconds; ``*_s`` properties convert to
    seconds for direct use in reports/logs.
    """

    prompt_eval_count: int = 0
    eval_count: int = 0
    load_duration_ns: int = 0
    prompt_eval_duration_ns: int = 0
    eval_duration_ns: int = 0
    total_duration_ns: int = 0
    wall_clock_s: float = Field(default=0.0, description="Measured client-side request duration.")

    @property
    def load_duration_s(self) -> float:
        return self.load_duration_ns / 1e9

    @property
    def prompt_eval_duration_s(self) -> float:
        return self.prompt_eval_duration_ns / 1e9

    @property
    def eval_duration_s(self) -> float:
        return self.eval_duration_ns / 1e9

    @property
    def total_duration_s(self) -> float:
        return self.total_duration_ns / 1e9


class StructuredChatResult(_Model):
    """Result of one non-streaming structured ``POST /api/chat`` call."""

    raw_content: str = Field(description="The assistant message content -- expected to be a JSON string.")
    metrics: OllamaGenerationMetrics
    model: str
    done: bool
    done_reason: str | None = None

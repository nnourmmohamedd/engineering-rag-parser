"""Deterministic, network-free fakes implementing :class:`LLMClient`.

Used by every fast test that exercises ``services/answerer`` or
``pipelines/answering_pipeline`` without a real Ollama server.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from engineering_rag.clients.ollama.errors import OllamaConnectionError, OllamaModelNotFoundError
from engineering_rag.clients.ollama.interface import LLMClient
from engineering_rag.clients.ollama.models import (
    OllamaGenerationMetrics,
    OllamaModelInfo,
    OllamaVersionInfo,
    StructuredChatResult,
)

__all__ = ["FakeLLMClient", "ScriptedResponse", "make_answer_payload", "scripted_json"]


def make_answer_payload(
    *,
    answer: str = "",
    insufficient_evidence: bool = False,
    insufficiency_reason: str | None = None,
    citations_used: list[str] | None = None,
    supporting_evidence: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "answer": answer,
        "insufficient_evidence": insufficient_evidence,
        "insufficiency_reason": insufficiency_reason,
        "citations_used": citations_used or [],
        "supporting_evidence": supporting_evidence or [],
    }


class ScriptedResponse:
    """One scripted outcome for a call to ``generate_structured``: raw content or a raised error."""

    def __init__(self, *, raw_content: str | None = None, raises: Exception | None = None) -> None:
        self.raw_content = raw_content
        self.raises = raises


class FakeLLMClient(LLMClient):
    """Returns scripted responses in order, or delegates to a callable for dynamic behavior.

    ``responses`` is consumed one call at a time; the last entry repeats once
    exhausted, so a test can script "first call malformed, second call
    valid" without needing to know exactly how many calls will happen.
    """

    def __init__(
        self,
        *,
        responses: list[ScriptedResponse] | None = None,
        on_generate: Callable[[str, str, dict[str, Any]], StructuredChatResult] | None = None,
        model_name: str = "qwen3:8b",
        digest: str = "fakedigest0000000000000000000000000000000000000000000000000000",
        installed_models: list[OllamaModelInfo] | None = None,
        healthy: bool = True,
    ) -> None:
        self._responses = responses or []
        self._on_generate = on_generate
        self._model_name = model_name
        self._digest = digest
        self._installed_models = installed_models
        self._healthy = healthy
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def health_check(self) -> bool:
        return self._healthy

    def version(self) -> OllamaVersionInfo:
        return OllamaVersionInfo(version="0.0.0-fake")

    def list_models(self) -> list[OllamaModelInfo]:
        if self._installed_models is not None:
            return self._installed_models
        return [
            OllamaModelInfo(
                name=self._model_name,
                digest=self._digest,
                size_bytes=1,
                parameter_size="8.2B",
                quantization_level="Q4_K_M",
                family="qwen3",
            )
        ]

    def model_info(self, model: str) -> OllamaModelInfo:
        for info in self.list_models():
            if info.name == model:
                return info
        raise OllamaModelNotFoundError(f"Model {model!r} not installed (fake)")

    def generate_structured(
        self, *, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> StructuredChatResult:
        self.calls.append((system_prompt, user_prompt, json_schema))

        if self._on_generate is not None:
            return self._on_generate(system_prompt, user_prompt, json_schema)

        if not self._responses:
            raise OllamaConnectionError("FakeLLMClient has no scripted responses and no on_generate callback")
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        scripted = self._responses[index]
        if scripted.raises is not None:
            raise scripted.raises
        return StructuredChatResult(
            raw_content=scripted.raw_content or "",
            metrics=OllamaGenerationMetrics(prompt_eval_count=100, eval_count=20, wall_clock_s=0.01),
            model=self._model_name,
            done=True,
            done_reason="stop",
        )


def scripted_json(payload: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(raw_content=json.dumps(payload))

"""Top-level answering configuration: ollama + context_builder + grounding + answering + logging.

Mirrors ``pipelines/retrieval_config.py``'s conventions exactly. Composes
independently-owned sections and adds the one cross-cutting invariant none of
them can validate alone: the whole token budget must fit inside the model's
real context window.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from engineering_rag.clients.ollama.config import OllamaConfig
from engineering_rag.services.answerer.config import AnsweringConfig
from engineering_rag.services.context_builder.config import ContextBuilderConfig
from engineering_rag.services.grounding.config import GroundingConfig

__all__ = ["AnsweringEvaluationConfig", "AnsweringPipelineConfig", "load_answering_config"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AnsweringLoggingConfig(_Frozen):
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class AnsweringEvaluationConfig(_Frozen):
    """Where the answering-specific ground-truth dataset and evaluation reports live.

    Deliberately separate from ``retrieval.evaluation`` (a different dataset,
    different questions: whether the *answer* refuses/cites/is grounded, not
    whether the *retrieved chunks* rank well).
    """

    dataset_path: Path = Path("data/eval/answering_ground_truth.jsonl")
    output_root: Path = Path("data/output/answering_evaluation")


class AnsweringPipelineConfig(_Frozen):
    """Composed, hashable configuration for one ``engrag-ask`` run."""

    profile: Literal["production"] = "production"

    answering: AnsweringConfig = AnsweringConfig()
    ollama: OllamaConfig = OllamaConfig()
    context_builder: ContextBuilderConfig = ContextBuilderConfig()
    grounding: GroundingConfig = GroundingConfig()
    evaluation: AnsweringEvaluationConfig = AnsweringEvaluationConfig()
    logging: AnsweringLoggingConfig = AnsweringLoggingConfig()

    output_root: Path = Path("data/output/answering")

    def effective_dict(self) -> dict[str, Any]:
        return json.loads(self.model_dump_json())

    def config_hash(self) -> str:
        payload = json.dumps(self.effective_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def _budget_fits_context_window(self) -> AnsweringPipelineConfig:
        cb = self.context_builder
        total = (
            cb.max_context_tokens
            + cb.reserved_system_tokens
            + cb.safety_margin_tokens
            + self.ollama.max_output_tokens
        )
        if total > self.ollama.context_window_tokens:
            raise ValueError(
                "Token budget does not fit the configured model context window: "
                f"context_builder.max_context_tokens ({cb.max_context_tokens}) + "
                f"context_builder.reserved_system_tokens ({cb.reserved_system_tokens}) + "
                f"context_builder.safety_margin_tokens ({cb.safety_margin_tokens}) + "
                f"ollama.max_output_tokens ({self.ollama.max_output_tokens}) = {total} tokens, "
                f"which exceeds ollama.context_window_tokens ({self.ollama.context_window_tokens})."
            )
        return self


def load_answering_config(path: Path | str | None = None, **overrides: Any) -> AnsweringPipelineConfig:
    """Load a full ``configs/answering_*.yaml`` profile, applying top-level overrides.

    Raises:
        FileNotFoundError: if an explicit path does not exist.
        ValueError: if the YAML does not describe a mapping, or the effective
            token budget does not fit inside the configured context window.
        pydantic.ValidationError: if the effective configuration is invalid.
    """
    data: dict[str, Any] = {}
    if path is not None:
        cfg_path = Path(path)
        if not cfg_path.is_file():
            raise FileNotFoundError(f"Config file not found: {cfg_path}")
        loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(
                f"Config file must contain a YAML mapping, got {type(loaded).__name__}: {cfg_path}"
            )
        data = loaded
    data.update({k: v for k, v in overrides.items() if v is not None})
    return AnsweringPipelineConfig.model_validate(data)

"""Validated, hashable configuration for the cross-encoder reranking stage."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = ["RerankerConfig"]

#: Resolved via `HfApi().model_info("BAAI/bge-reranker-base").sha` on 2026-08-25.
DEFAULT_RERANKER_REVISION = "2cfc18c9415c912f9d8155881c133215df768a70"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RerankerConfig(_Frozen):
    """Cross-encoder reranking parameters. ``enabled=False`` is the production default."""

    enabled: bool = False
    model_name: str = Field(default="BAAI/bge-reranker-base")
    model_revision: str | None = Field(
        default=DEFAULT_RERANKER_REVISION,
        description="Pinned Hugging Face revision for reproducibility. Null resolves the latest revision.",
    )
    candidate_top_k: int = Field(
        default=20, gt=0, description="How many fused/vector candidates are handed to the cross-encoder."
    )
    final_top_k: int = Field(default=5, gt=0, description="How many reranked results are returned.")
    batch_size: int = Field(default=8, gt=0)
    max_length: int = Field(default=512, gt=0, description="Max token length per query-document pair.")
    device: Literal["auto", "cpu", "cuda"] = "cpu"

    @model_validator(mode="after")
    def _validate(self) -> RerankerConfig:
        if self.candidate_top_k < self.final_top_k:
            raise ValueError(
                f"reranker.candidate_top_k ({self.candidate_top_k}) must be >= "
                f"reranker.final_top_k ({self.final_top_k})"
            )
        return self

    def effective_dict(self) -> dict[str, Any]:
        return json.loads(self.model_dump_json())

    def config_hash(self) -> str:
        payload = json.dumps(self.effective_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

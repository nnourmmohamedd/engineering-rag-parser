"""Validated, hashable configuration for the answering stage itself (not Ollama, not context building)."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["AnsweringConfig"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AnsweringConfig(_Frozen):
    """Answer-generation policy: which retrieval mode, which prompt version, repair policy."""

    default_retrieval_mode: Literal["vector", "hybrid", "vector-rerank", "hybrid-rerank"] = "vector"
    prompt_version: str = "1.0.0"
    allow_single_repair: bool = Field(
        default=True,
        description="At most one structured-repair attempt for malformed JSON / unknown citations / missing "
        "required schema fields. Never unbounded, never used for deterministic infrastructure failures "
        "(connection/timeout errors are never retried by re-prompting the model).",
    )

    def effective_dict(self) -> dict[str, Any]:
        return json.loads(self.model_dump_json())

    def config_hash(self) -> str:
        payload = json.dumps(self.effective_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

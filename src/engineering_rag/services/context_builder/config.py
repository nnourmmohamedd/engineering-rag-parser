"""Validated, hashable configuration for the context-building stage.

Mirrors ``services/chunker/config.py`` and ``services/reranker/config.py``:
frozen, ``extra="forbid"`` Pydantic models so a typo in a profile file is a
configuration error, never a silently-ignored key.

The token-budget fields here are combined with ``ollama.context_window_tokens``
and ``ollama.max_output_tokens`` by
:class:`engineering_rag.pipelines.answering_config.AnsweringPipelineConfig`,
which is the one place that validates the whole budget fits inside the
model's real context window (this module validates only its own internal
ordering).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = ["ContextBuilderConfig", "TokenizerConfig"]

#: Resolved via `HfApi().model_info("Qwen/Qwen3-8B").sha` on 2026-08-25. Tokenizer
#: files only (tokenizer.json/tokenizer_config.json/vocab.json/merges.txt) are
#: downloaded and cached -- the multi-GB model weights are never fetched.
DEFAULT_QWEN3_TOKENIZER_REVISION = "b968826d9c46dd6066d109eabc6255188de91218"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TokenizerConfig(_Frozen):
    """Which :class:`~engineering_rag.services.context_builder.token_counter.TokenCounter` backend to use.

    ``qwen3`` loads the real ``Qwen/Qwen3-8B`` tokenizer (tokenizer files
    only) via ``transformers.AutoTokenizer`` and counts tokens exactly as
    that tokenizer would. ``conservative_fallback`` is a deterministic,
    network-free character-count heuristic tuned to over-count (never
    under-count) relative to observed Qwen3 tokenization on this project's
    engineering-document text -- see
    ``docs/answering/GROUNDED_ANSWERING_ARCHITECTURE.md`` for the measured
    comparison and its honest limitations. It is NOT an exact token count.
    """

    backend: Literal["qwen3", "conservative_fallback"] = "qwen3"
    model_name: str = "Qwen/Qwen3-8B"
    revision: str | None = DEFAULT_QWEN3_TOKENIZER_REVISION
    trust_remote_code: bool = False
    chars_per_token_fallback: float = Field(
        default=3.0,
        gt=0,
        description="Conservative fallback divisor: token_count = ceil(len(text) / this). Deliberately "
        "below the ~3.5-4 chars/token typically observed for Qwen3 on English engineering text, so the "
        "fallback always over-counts rather than under-counts and risks exceeding the real budget.",
    )


class ContextBuilderConfig(_Frozen):
    """Context selection, deduplication, diversity, neighbor-expansion, and budget parameters."""

    tokenizer: TokenizerConfig = TokenizerConfig()

    max_context_tokens: int = Field(
        default=5000, gt=0, description="Hard ceiling on the token count of the rendered evidence text."
    )
    reserved_system_tokens: int = Field(
        default=900,
        ge=0,
        description="Budget reserved for the system prompt + user-question wrapper + citation-id list + "
        "chat-template role markers. Measured evidence: the v1.0.0 system prompt is 672 tokens under the "
        "Qwen3 tokenizer; +~50 for the question/citation-id wrapper and template role tokens. 900 leaves "
        "real headroom over that measured ~720-750 total.",
    )
    safety_margin_tokens: int = Field(
        default=400,
        ge=0,
        description="Additional buffer absorbing per-source <SOURCE> delimiter overhead (counted in the "
        "final rendered context_text but not in the per-chunk budgeting pass) and any token-count "
        "estimation error, particularly under the conservative fallback counter.",
    )

    max_sources: int = Field(default=10, gt=0, description="Hard ceiling on selected sources per answer.")
    max_sources_per_document: int = Field(default=8, gt=0)
    max_sources_per_section: int = Field(default=3, gt=0)

    deduplicate_content: bool = Field(
        default=True, description="Exclude a candidate whose content_hash duplicates an already-selected one."
    )

    neighbor_expansion_enabled: bool = Field(default=True)
    neighbor_window: int = Field(
        default=1, ge=0, le=3, description="How many previous/next chunks to consider per direct hit."
    )

    def effective_dict(self) -> dict[str, Any]:
        return json.loads(self.model_dump_json())

    def config_hash(self) -> str:
        payload = json.dumps(self.effective_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def _ordering(self) -> ContextBuilderConfig:
        if self.max_sources_per_document > self.max_sources:
            raise ValueError("context_builder.max_sources_per_document must be <= max_sources")
        if self.max_sources_per_section > self.max_sources:
            raise ValueError("context_builder.max_sources_per_section must be <= max_sources")
        return self

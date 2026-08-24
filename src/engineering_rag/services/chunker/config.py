"""Validated, hashable configuration for the chunker service.

Mirrors :mod:`engineering_rag.services.parser.config`: a public YAML contract
decoupled from any one library's option classes, frozen and ``extra="forbid"``
so a typo in a profile file is a configuration error, not a silently ignored
key. Every effective configuration is hashed (:meth:`ChunkerConfig.config_hash`)
and recorded in the run manifest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "ChunkerConfig",
    "TokenizerOptions",
    "load_config",
]


class _Frozen(BaseModel):
    """Immutable, strict base: an unknown key is a configuration error, not a typo we ignore."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class TokenizerOptions(_Frozen):
    """Which tokenizer measures chunk size, and how it is resolved.

    ``sentence-transformers/all-MiniLM-L6-v2`` is the default: a small
    (22M-parameter), permissively-licensed (Apache-2.0), widely-used English
    sentence-embedding model. Its tokenizer (a WordPiece/BERT tokenizer, a few
    hundred KB) is downloaded and cached via ``transformers.AutoTokenizer`` —
    the embedding model's weights themselves are never fetched, since only
    token counting is needed at this stage. ``max_tokens`` defaults to 256,
    matching this model's own trained ``max_seq_length`` (its
    ``sentence_bert_config.json``), not the tokenizer's raw architectural
    limit (512) — chunks sized for a *different* limit would silently
    truncate on encoding once embeddings are added in a later milestone.
    """

    name: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="Hugging Face model id (or local path) whose tokenizer measures chunk size.",
    )
    revision: str | None = Field(
        default=None, description="Optional pinned model revision/commit for reproducibility."
    )
    trust_remote_code: bool = Field(
        default=False, description="Passed to AutoTokenizer.from_pretrained. Off by default for safety."
    )


class ChunkerConfig(_Frozen):
    """Top-level, hashable chunker configuration."""

    profile: Literal["production"] = "production"

    tokenizer: TokenizerOptions = TokenizerOptions()

    max_tokens: int = Field(
        default=256,
        gt=0,
        description="Hard ceiling: an ordinary (non-atomic-overflow) chunk must never exceed this "
        "many tokens, as measured by `tokenizer`. Matches the default tokenizer's own trained "
        "max_seq_length. Raise only if the target embedding model supports a longer context.",
    )
    target_tokens: int = Field(
        default=180,
        gt=0,
        description="Soft target for recursively-split text chunks: the splitter aims for chunks "
        "near this size (leaving headroom below max_tokens for heading/caption context added to "
        "retrieval_text). Lower values produce more, more-focused chunks; higher values approach "
        "max_tokens and reduce focus.",
    )
    min_chunk_tokens: int = Field(
        default=40,
        ge=0,
        description="Below this size, a chunk is a *candidate* for safe small-sibling merging "
        "(see merge_small_chunks). Too high risks merging unrelated short sections together; "
        "too low leaves many fragment-sized chunks that retrieve poorly.",
    )
    text_overlap_tokens: int = Field(
        default=32,
        ge=0,
        description="Token overlap between adjacent recursively-split TEXT children only — never "
        "applied to hierarchical (unsplit) chunks or to tables/lists/code/equations/figures. "
        "Too much overlap wastes index space on duplication; too little risks a fact split exactly "
        "at a chunk boundary losing surrounding context.",
    )
    recursive_separators: tuple[str, ...] = Field(
        default=("\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " ", ""),
        description="Ordered strongest-to-weakest split boundaries for recursive text splitting "
        "(paragraph, line, sentence, clause, word, hard character fallback last).",
    )

    merge_small_chunks: bool = Field(
        default=True,
        description="Whether undersized (< min_chunk_tokens) sibling chunks are merged when doing "
        "so is provably safe (same document, same content type, same heading path, adjacent in "
        "reading order, result still <= max_tokens). See services/chunker/merging.py.",
    )
    repeat_table_headers: bool = Field(
        default=True,
        description="When a table is split into row-group fragments, repeat the column-header row "
        "in every fragment so each fragment is independently interpretable.",
    )
    include_heading_context: bool = Field(
        default=True,
        description="Whether retrieval_text is prefixed with the chunk's heading path / section "
        "title / captions. `text` is never altered by this flag — only `retrieval_text` is.",
    )
    allowed_atomic_overflow: bool = Field(
        default=True,
        description="Whether a single atomic, unsplittable unit (one equation, one table cell, one "
        "list item) that alone exceeds max_tokens is permitted to ship as an explicitly flagged "
        "oversized chunk rather than being corrupted by a forced split. If False, such input causes "
        "a hard validation failure instead.",
    )

    output_root: Path = Field(
        default=Path("data/output/chunker"),
        description="Base directory for chunker run artifacts (overridable via CLI --output).",
    )

    strict: bool = Field(default=False, description="Treat warnings as failures (CI gate).")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @model_validator(mode="after")
    def _ordering(self) -> ChunkerConfig:
        if self.min_chunk_tokens >= self.max_tokens:
            raise ValueError("min_chunk_tokens must be < max_tokens")
        if self.target_tokens > self.max_tokens:
            raise ValueError("target_tokens must be <= max_tokens")
        if self.text_overlap_tokens >= self.target_tokens:
            raise ValueError("text_overlap_tokens must be < target_tokens")
        if not self.recursive_separators or self.recursive_separators[-1] != "":
            raise ValueError(
                "recursive_separators must end with '' (the hard character-level fallback), "
                "so a single word longer than target_tokens is still splittable"
            )
        return self

    def effective_dict(self) -> dict[str, Any]:
        """JSON-safe view of the effective configuration, suitable for a manifest."""
        return json.loads(self.model_dump_json())

    def config_hash(self) -> str:
        """Stable SHA-256 over the effective configuration."""
        payload = json.dumps(self.effective_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def with_overrides(self, **overrides: Any) -> ChunkerConfig:
        """Return a new config with top-level fields replaced (frozen-model friendly)."""
        return self.model_copy(update=overrides)


def load_config(path: Path | str | None = None, **overrides: Any) -> ChunkerConfig:
    """Load a YAML config file, applying top-level overrides.

    A missing ``path`` yields the built-in (production) defaults.

    Raises:
        FileNotFoundError: if an explicit path does not exist.
        ValueError: if the YAML does not describe a mapping.
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
    return ChunkerConfig.model_validate(data)

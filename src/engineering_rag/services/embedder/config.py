"""Validated, hashable configuration for the embedding service.

Mirrors :mod:`engineering_rag.services.chunker.config`: frozen, ``extra="forbid"``
pydantic models with cross-field validation at parse time, plus
``effective_dict()`` / ``config_hash()`` for manifest recording.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = ["EmbedderConfig", "load_config"]


class _Frozen(BaseModel):
    """Immutable, strict base: an unknown key is a configuration error, not a typo we ignore."""

    model_config = ConfigDict(frozen=True, extra="forbid")


#: The literal instruction prefix BGE expects on *query* text (not passages).
#: See BAAI/bge-base-en-v1.5's model card. Stored (not hardcoded) so it is
#: recorded verbatim in every index manifest.
DEFAULT_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class EmbedderConfig(_Frozen):
    """Top-level, hashable embedding-service configuration."""

    model_name: str = Field(
        default="BAAI/bge-base-en-v1.5",
        description="SentenceTransformers model id (or local path) used to embed passages and queries.",
    )
    model_revision: str | None = Field(
        default=None, description="Optional pinned model revision/commit for reproducibility."
    )
    trust_remote_code: bool = Field(
        default=False, description="Passed to SentenceTransformer(). Off by default."
    )

    expected_dimension: int = Field(
        default=768, gt=0, description="Output embedding dimensionality this model must produce."
    )
    maximum_sequence_length: int = Field(
        default=512, gt=0, description="Model's trained max_seq_length; informational + used for validation."
    )
    normalize_embeddings: bool = Field(default=True, description="L2-normalize every output vector.")
    batch_size: int = Field(default=32, gt=0, description="Encode batch size.")
    device: Literal["auto", "cpu", "cuda"] = Field(
        default="auto", description="Device selection: auto picks CUDA if available, else CPU."
    )

    document_field: str = Field(
        default="retrieval_text", description="Chunk JSONL field embedded as a passage."
    )
    document_prefix: str = Field(
        default="", description="Prefix prepended to passages before embedding (none by default)."
    )
    query_prefix: str = Field(
        default=DEFAULT_QUERY_PREFIX,
        min_length=1,
        description="Instruction prefix prepended to queries only.",
    )

    offline: bool = Field(
        default=False,
        description="If true, sets HF_HUB_OFFLINE=1 / local_files_only so the model must already be cached.",
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @model_validator(mode="after")
    def _validate(self) -> EmbedderConfig:
        if not self.model_name.strip():
            raise ValueError("model_name must not be empty")
        if not self.query_prefix.strip():
            raise ValueError("query_prefix must not be empty/whitespace-only")
        return self

    def effective_dict(self) -> dict[str, Any]:
        """JSON-safe view of the effective configuration, suitable for a manifest."""
        return json.loads(self.model_dump_json())

    def config_hash(self) -> str:
        """Stable SHA-256 over the effective configuration."""
        payload = json.dumps(self.effective_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def with_overrides(self, **overrides: Any) -> EmbedderConfig:
        return self.model_copy(update=overrides)


def load_config(path: Path | str | None = None, **overrides: Any) -> EmbedderConfig:
    """Load a section of an indexing YAML profile (the ``embedding:`` mapping).

    Prefer :func:`engineering_rag.pipelines.indexing_pipeline.load_indexing_config`
    for CLI use, which loads the full ``configs/indexing_*.yaml`` document
    (embedding + chroma + validation + logging sections). This function loads
    a bare embedder-only mapping — useful for unit tests and library callers
    that only need the embedding half.
    """
    import yaml

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
    return EmbedderConfig.model_validate(data)

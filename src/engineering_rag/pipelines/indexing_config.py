"""Top-level indexing configuration: embedding + chroma + validation + logging.

Mirrors ``services/chunker/config.py``'s conventions but composes two
already-frozen sub-configs (``EmbedderConfig``, ``ChromaConfig``) plus a
validation section that is specific to the indexing pipeline (not owned by
either the embedder or the Chroma adapter individually, since it checks
cross-cutting things like tokenizer-family compatibility).

Every field is validated **at parse time**, before any model is loaded or any
database is touched — a malformed profile fails fast with a clear pydantic
error, never partway through an expensive run.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from engineering_rag.databases.chroma.config import ChromaConfig
from engineering_rag.services.embedder.config import EmbedderConfig

__all__ = ["IndexingConfig", "IndexValidationConfig", "load_indexing_config"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class IndexValidationConfig(_Frozen):
    """Cross-cutting acceptance-gate configuration for the indexing pipeline."""

    norm_tolerance: float = Field(
        default=1e-3, gt=0, description="Allowed deviation of vector L2 norm from 1.0."
    )
    require_all_chunks: bool = Field(
        default=True, description="Every chunk_id in chunks.jsonl must land in the collection."
    )
    require_round_trip_match: bool = Field(
        default=True,
        description="Stored document/vector must match what was written, verified by re-fetching.",
    )
    require_model_tokenizer_match: bool = Field(
        default=True,
        description="Reject ingestion if the chunk run's tokenizer family does not match the embedding model's.",
    )
    self_retrieval_sample_size: int = Field(
        default=20, ge=0, description="Number of chunks sampled for the self-retrieval rank-1 integrity test."
    )
    fail_on_model_mismatch: bool = Field(
        default=True,
        description="An existing collection with incompatible identity metadata is a hard failure.",
    )


class IndexingLoggingConfig(_Frozen):
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class IndexingConfig(_Frozen):
    """Composed, hashable configuration for one indexing run."""

    profile: Literal["production"] = "production"

    embedding: EmbedderConfig = EmbedderConfig()
    chroma: ChromaConfig = ChromaConfig()
    validation: IndexValidationConfig = IndexValidationConfig()
    logging: IndexingLoggingConfig = IndexingLoggingConfig()

    output_root: Path = Field(
        default=Path("data/output/indexing"),
        description="Base directory for per-run index report artifacts (the Chroma persistence "
        "directory itself is separate and stable — see chroma.persistence_path).",
    )
    strict: bool = Field(default=False, description="Treat warnings as failures (CI gate).")

    @model_validator(mode="after")
    def _validate(self) -> IndexingConfig:
        if self.embedding.expected_dimension != 768:
            raise ValueError(
                f"this profile requires expected_dimension == 768, got {self.embedding.expected_dimension}"
            )
        return self

    def effective_dict(self) -> dict[str, Any]:
        return json.loads(self.model_dump_json())

    def config_hash(self) -> str:
        payload = json.dumps(self.effective_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_indexing_config(path: Path | str | None = None, **overrides: Any) -> IndexingConfig:
    """Load a full ``configs/indexing_*.yaml`` profile, applying top-level overrides.

    Raises:
        FileNotFoundError: if an explicit path does not exist.
        ValueError: if the YAML does not describe a mapping.
        pydantic.ValidationError: if the effective configuration is invalid —
            raised here, before any model load or database connection.
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
    return IndexingConfig.model_validate(data)

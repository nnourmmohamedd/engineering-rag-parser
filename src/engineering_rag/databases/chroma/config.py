"""Validated, hashable configuration for the Chroma storage adapter.

Frozen, ``extra="forbid"`` pydantic model, validated at parse time before any
database or model is touched — mirrors ``services/chunker/config.py`` and
``services/embedder/config.py``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = ["ChromaConfig", "validate_collection_name"]

_COLLECTION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,510}[A-Za-z0-9]$")
_IPV4_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")

#: Rules confirmed by direct introspection of chromadb 1.5.9's own validation
#: error messages (``chromadb.api.rust`` create_collection), not assumed from
#: older tutorials: 3-512 characters from [a-zA-Z0-9._-], must start/end with
#: an alphanumeric character, must not contain two consecutive periods, and
#: must not be a valid IPv4 address.


def validate_collection_name(name: str) -> None:
    """Raise ``ValueError`` if ``name`` violates Chroma's own collection-name constraints."""
    if not (3 <= len(name) <= 512):
        raise ValueError(f"collection name must be 3-512 characters, got {len(name)}: {name!r}")
    if not _COLLECTION_NAME_RE.match(name):
        raise ValueError(
            "collection name must start/end with an alphanumeric character and contain only "
            f"letters, digits, underscore, hyphen or period: {name!r}"
        )
    if ".." in name:
        raise ValueError(f"collection name must not contain two consecutive periods: {name!r}")
    if _IPV4_RE.match(name):
        raise ValueError(f"collection name must not be a valid IPv4 address: {name!r}")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ChromaConfig(_Frozen):
    """Top-level, hashable Chroma adapter configuration."""

    persistence_path: Path = Field(
        default=Path("data/output/databases/chroma"),
        description="Base directory for the persistent Chroma client (stable across runs, not per-run).",
    )
    collection_name: str = Field(default="engineering_documents_v1", description="Chroma collection name.")
    distance_metric: Literal["cosine"] = Field(
        default="cosine", description="hnsw:space distance metric. Only cosine is supported by this adapter."
    )
    ingestion_batch_size: int = Field(default=100, gt=0, description="Records per Chroma add() call.")
    idempotent: bool = Field(
        default=True, description="Same id + same content hash on rerun is a no-op skip, not an error."
    )
    allow_rebuild: bool = Field(
        default=False, description="Whether --rebuild (destructive collection replacement) is permitted."
    )
    telemetry: bool = Field(
        default=False, description="Chroma's anonymized_telemetry setting. Off by default."
    )

    @model_validator(mode="after")
    def _validate(self) -> ChromaConfig:
        try:
            validate_collection_name(self.collection_name)
        except ValueError as exc:
            raise ValueError(f"invalid collection_name: {exc}") from exc
        return self

    def effective_dict(self) -> dict[str, Any]:
        import json

        return json.loads(self.model_dump_json())

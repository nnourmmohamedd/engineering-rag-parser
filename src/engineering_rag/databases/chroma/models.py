"""Chroma-adapter domain models: collection metadata contract, ingestion results.

Independent of sentence-transformers: this package never imports it — a
:class:`CollectionIdentity` is built from plain values the caller supplies.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CollectionIdentity",
    "IngestionOutcome",
]

#: Bumped whenever the *shape* of what we store per-record in Chroma changes
#: (new required metadata field, different id scheme, ...).
INDEX_SCHEMA_VERSION = "1.0.0"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CollectionIdentity(_Model):
    """The identity fields stored in a collection's own metadata and checked on every open.

    An existing collection whose stored identity disagrees with the current
    run's configuration is a hard failure (:class:`~.errors.CollectionMismatchError`) —
    never silently overwritten or silently used as-is.
    """

    model_name: str
    embedding_dimension: int
    distance_metric: str
    index_schema_version: str = INDEX_SCHEMA_VERSION
    tokenizer_name: str
    corpus_id: str = Field(
        default="", description="Free-form identity of the corpus/index, e.g. a config hash."
    )

    def as_chroma_metadata(self) -> dict[str, str | int | float | bool]:
        return {
            "hnsw:space": self.distance_metric,
            "model_name": self.model_name,
            "embedding_dimension": self.embedding_dimension,
            "distance_metric": self.distance_metric,
            "index_schema_version": self.index_schema_version,
            "tokenizer_name": self.tokenizer_name,
            "corpus_id": self.corpus_id,
        }

    def mismatches(self, other: dict[str, Any]) -> list[str]:
        """Return a human-readable list of fields that disagree with a stored metadata dict."""
        problems = []
        for field_name, expected in (
            ("model_name", self.model_name),
            ("embedding_dimension", self.embedding_dimension),
            ("distance_metric", self.distance_metric),
            ("index_schema_version", self.index_schema_version),
            ("tokenizer_name", self.tokenizer_name),
        ):
            actual = other.get(field_name)
            if actual != expected:
                problems.append(f"{field_name}: expected {expected!r}, collection has {actual!r}")
        return problems


class IngestionOutcome(_Model):
    """Result of ingesting one batch or one full run — see ``ingestion_report.json``."""

    expected_ids: list[str] = Field(default_factory=list)
    inserted_ids: list[str] = Field(default_factory=list)
    existing_identical_ids: list[str] = Field(default_factory=list)
    rejected_ids: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    final_count: int = 0

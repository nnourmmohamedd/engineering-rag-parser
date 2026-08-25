"""Indexing pipeline domain models: the output contract for one indexing run.

Mirrors ``services/chunker/models.py``'s ``ChunkManifest`` /
``ChunkValidationReport`` shape and severity semantics exactly, so the two
report families read the same way to a human or a future automated check.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "INDEX_MANIFEST_SCHEMA_VERSION",
    "IndexManifest",
    "IndexRunStatus",
    "IndexSeverity",
    "IndexValidationCheck",
    "IndexValidationReport",
]

INDEX_MANIFEST_SCHEMA_VERSION = "1.0.0"


class IndexRunStatus(str, Enum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    FAIL = "FAIL"


class IndexSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IndexValidationCheck(_Model):
    check_id: str
    title: str
    passed: bool
    severity: IndexSeverity
    gate: bool = Field(default=False, description="True when this check is an acceptance gate.")
    summary: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    remediation: str = ""


class IndexValidationReport(_Model):
    status: IndexRunStatus
    strict: bool = False
    generated_at_utc: datetime
    checks: list[IndexValidationCheck] = Field(default_factory=list)
    human_review_items: list[str] = Field(default_factory=list)

    @property
    def failed_gates(self) -> list[IndexValidationCheck]:
        return [c for c in self.checks if c.gate and not c.passed]

    @property
    def warnings(self) -> list[IndexValidationCheck]:
        return [c for c in self.checks if not c.passed and c.severity is IndexSeverity.WARNING]

    def compute_status(self, strict: bool) -> IndexRunStatus:
        if any(not c.passed and c.severity is IndexSeverity.CRITICAL for c in self.checks):
            return IndexRunStatus.FAIL
        has_warnings = any(not c.passed and c.severity is IndexSeverity.WARNING for c in self.checks)
        if has_warnings:
            return IndexRunStatus.FAIL if strict else IndexRunStatus.PASS_WITH_WARNINGS
        return IndexRunStatus.PASS


class IndexManifest(_Model):
    """Everything needed to reproduce, audit or invalidate an indexing run."""

    schema_version: str = INDEX_MANIFEST_SCHEMA_VERSION
    run_id: str
    generated_at_utc: datetime

    collection_name: str
    chroma_path: str

    input_chunks_jsonl_path: str
    input_chunks_jsonl_sha256: str
    input_chunk_run_id: str
    source_documents: list[dict[str, Any]] = Field(default_factory=list)

    chunk_count: int
    content_type_counts: dict[str, int] = Field(default_factory=dict)

    model_name: str
    resolved_model_revision: str | None = None
    tokenizer_name: str
    embedding_dimension: int
    max_seq_length: int
    normalize_embeddings: bool
    distance_metric: str
    query_prefix: str
    document_prefix: str
    batch_size: int
    device: str

    versions: dict[str, str] = Field(default_factory=dict)

    collection_count_after_run: int = 0
    vector_validation_stats: dict[str, Any] = Field(default_factory=dict)

    config_hash: str
    status: str = "FAIL"
    warnings: list[str] = Field(default_factory=list)
    timings_s: dict[str, float] = Field(default_factory=dict)

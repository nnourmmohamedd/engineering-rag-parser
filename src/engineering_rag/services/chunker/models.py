"""Chunker domain models: the output contract and the shared vocabulary of
manifests and validation reports.

These are the stable, versioned data the chunker exists to produce. Keeping
them free of any Docling import means a ``chunks.jsonl`` written today still
loads after a Docling upgrade.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CHUNK_SCHEMA_VERSION",
    "Chunk",
    "ChunkManifest",
    "ChunkValidationCheck",
    "ChunkValidationReport",
    "ContentType",
    "ProvenanceRecord",
    "RunStatus",
    "Severity",
    "SplitMethod",
    "TableFragmentMeta",
]

CHUNK_SCHEMA_VERSION = "1.0.0"


class ContentType(str, Enum):
    """What kind of source content a chunk represents."""

    TEXT = "text"
    TABLE = "table"
    LIST = "list"
    CODE = "code"
    EQUATION = "equation"
    FIGURE = "figure"


class SplitMethod(str, Enum):
    """How a chunk reached its final form."""

    HIERARCHICAL = "hierarchical"
    RECURSIVE_TEXT = "recursive_text"
    TABLE_ROWS = "table_rows"
    LIST_ITEMS = "list_items"
    CODE_BLOCK = "code_block"
    EQUATION_ATOMIC = "equation_atomic"
    FIGURE = "figure"
    MERGED = "merged"


class RunStatus(str, Enum):
    """Terminal status of a chunking run."""

    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    FAIL = "FAIL"


class Severity(str, Enum):
    """Severity of one validation check."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProvenanceRecord(_Model):
    """One page/bbox provenance entry, carried over from the source DoclingDocument."""

    page_no: int
    bbox: tuple[float, float, float, float] | None = Field(
        default=None, description="(l, t, r, b) in PDF points, as recorded by Docling."
    )
    charspan: tuple[int, int] | None = None


class TableFragmentMeta(_Model):
    """Metadata specific to a TABLE chunk, present only when content_type == table."""

    num_rows: int
    num_cols: int
    is_fragment: bool = False
    fragment_index: int | None = None
    total_fragments: int | None = None
    header_repeated: bool = False
    detected_label: str | None = None


class Chunk(_Model):
    """One retrieval-ready chunk record — one line of ``chunks.jsonl``."""

    schema_version: str = CHUNK_SCHEMA_VERSION
    chunk_id: str
    document_id: str
    source_filename: str
    source_sha256: str
    chunk_index: int

    content_type: ContentType
    text: str = Field(description="Faithful content — never invents facts.")
    retrieval_text: str = Field(
        description="text, optionally prefixed with heading/caption context for embedding. "
        "Never adds facts not present in the source."
    )
    token_count: int
    tokenizer_name: str

    heading_path: list[str] = Field(default_factory=list)
    section_title: str | None = None
    captions: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list, description="Docling DocItemLabel values contributing.")
    page_numbers: list[int] = Field(default_factory=list)
    provenance: list[ProvenanceRecord] = Field(default_factory=list)
    source_element_refs: list[str] = Field(default_factory=list)

    parent_chunk_id: str | None = None
    previous_chunk_id: str | None = None
    next_chunk_id: str | None = None
    merged_from_chunk_ids: list[str] | None = None

    split_method: SplitMethod
    was_recursively_split: bool = False
    overlap_tokens_before: int = 0

    table_metadata: TableFragmentMeta | None = None
    figure_asset_path: str | None = None
    figure_page_no: int | None = None

    is_atomic_overflow: bool = Field(
        default=False,
        description="True when this chunk exceeds max_tokens because it is an "
        "explicitly-permitted, unsplittable atomic unit (allowed_atomic_overflow).",
    )

    parser_warnings: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ChunkManifest(_Model):
    """Everything needed to reproduce, audit or invalidate a chunking run."""

    run_id: str
    chunker_version: str
    generated_at_utc: datetime
    source: dict[str, Any]
    config_hash: str
    effective_config: dict[str, Any]
    tokenizer: dict[str, Any]
    chunk_count: int
    content_type_counts: dict[str, int]
    token_stats: dict[str, float]
    recursively_split_count: int
    merged_count: int
    warnings: list[str] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    versions: dict[str, str] = Field(default_factory=dict)
    status: str = "FAIL"
    timings_s: dict[str, float] = Field(default_factory=dict)


class ChunkValidationCheck(_Model):
    """One validation check with its own severity, evidence and remediation."""

    check_id: str
    title: str
    passed: bool
    severity: Severity
    gate: bool = Field(default=False, description="True when this check is an acceptance gate.")
    summary: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    remediation: str = ""


class ChunkValidationReport(_Model):
    """Aggregated validation outcome written to ``validation_report.json``."""

    status: RunStatus
    strict: bool = False
    generated_at_utc: datetime
    checks: list[ChunkValidationCheck] = Field(default_factory=list)
    human_review_items: list[str] = Field(default_factory=list)

    @property
    def failed_gates(self) -> list[ChunkValidationCheck]:
        return [c for c in self.checks if c.gate and not c.passed]

    @property
    def warnings(self) -> list[ChunkValidationCheck]:
        return [c for c in self.checks if not c.passed and c.severity is Severity.WARNING]

    def compute_status(self, strict: bool) -> RunStatus:
        if any(not c.passed and c.severity is Severity.CRITICAL for c in self.checks):
            return RunStatus.FAIL
        has_warnings = any(not c.passed and c.severity is Severity.WARNING for c in self.checks)
        if has_warnings:
            return RunStatus.FAIL if strict else RunStatus.PASS_WITH_WARNINGS
        return RunStatus.PASS

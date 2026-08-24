"""Domain models: the shared vocabulary of manifests, inventories and reports.

These types are the stable contract between stages. The preflight module and
the Docling parser both produce them, the validators consume them, and the run
manifest serialises them. Keeping them free of any Docling import means a
manifest written today still loads after a Docling upgrade.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CheckResult",
    "DocumentInventory",
    "PageCoverage",
    "PageInventory",
    "PictureFinding",
    "RunStatus",
    "Severity",
    "SourceManifest",
    "TableFinding",
    "ValidationReport",
]


class RunStatus(str, Enum):
    """Terminal status of a run. Mirrors the acceptance-gate vocabulary."""

    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    FAIL = "FAIL"


class Severity(str, Enum):
    """Severity of an individual validation check.

    ``CRITICAL`` maps to an acceptance gate: any critical failure forces
    ``RunStatus.FAIL``. ``WARNING`` forces ``PASS_WITH_WARNINGS`` (or ``FAIL``
    in strict mode). ``INFO`` never changes status.
    """

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# Preflight (independent, non-Docling) source inventory
# --------------------------------------------------------------------------


class ImageBlock(_Model):
    """One raster image placed on a page, as reported by the PDF page objects."""

    width_px: int | None = None
    height_px: int | None = None
    bbox: tuple[float, float, float, float] | None = Field(
        default=None, description="(x0, y0, x1, y1) in PDF points, origin bottom-left."
    )
    area_fraction: float | None = Field(default=None, description="Fraction of page area covered.")
    is_repeated: bool = Field(
        default=False,
        description="True when this exact (bbox, pixel-size) signature recurs across the document, "
        "i.e. it is page furniture (banner, watermark) rather than a figure.",
    )


class SourcePage(_Model):
    """Independent per-page measurements taken *without* Docling."""

    page_no: int = Field(description="1-based page number.")
    width_pt: float
    height_pt: float
    rotation: int = 0
    char_count: int = 0
    word_count: int = 0
    line_count: int = 0
    text_sha256: str = Field(
        description="SHA-256 of the normalised page text; enables cheap change detection."
    )
    text_sample: str = Field(
        default="", description="Short, redaction-limited excerpt for human orientation."
    )
    image_count: int = 0
    images: list[ImageBlock] = Field(default_factory=list)
    image_area_fraction: float = 0.0
    substantive_image_count: int = Field(
        default=0,
        description="Images whose (bbox, pixel-size) signature does NOT repeat across the document, "
        "i.e. real figures rather than the banner/watermark furniture.",
    )
    substantive_image_area_fraction: float = 0.0
    annotation_count: int = 0
    link_count: int = 0
    is_empty: bool = False
    is_sparse_text: bool = False
    is_image_heavy: bool = False
    needs_visual_review: bool = Field(
        default=False,
        description="True when the page carries any substantive image, is sparse, or is empty. Driven by "
        "presence rather than area: a small-but-real diagram must not escape review on a size threshold.",
    )
    header_candidates: list[str] = Field(default_factory=list)
    footer_candidates: list[str] = Field(default_factory=list)


class FurnitureCandidate(_Model):
    """A line of text that repeats across pages in a stable vertical band."""

    text: str
    normalized: str
    pages: list[int]
    page_fraction: float
    band: Literal["header", "footer", "body"]
    kind: Literal["header", "footer", "page_number", "watermark", "website", "other"]


class SourceManifest(_Model):
    """The full independent source inventory written to ``source/manifest.json``."""

    filename: str
    byte_size: int
    sha256: str
    mime_guess: str
    magic_ok: bool = Field(description="True when the file really begins with a %PDF- header.")
    pdf_version: str | None = None
    is_encrypted: bool = False
    page_count: int = 0
    metadata: dict[str, str] = Field(default_factory=dict)
    outline_entries: list[dict[str, Any]] = Field(default_factory=list)
    fonts: list[str] = Field(default_factory=list)
    embedded_files: list[str] = Field(default_factory=list)
    total_char_count: int = 0
    total_word_count: int = 0
    total_image_count: int = 0
    pages: list[SourcePage] = Field(default_factory=list)
    furniture_candidates: list[FurnitureCandidate] = Field(default_factory=list)
    sparse_pages: list[int] = Field(default_factory=list)
    image_heavy_pages: list[int] = Field(default_factory=list)
    empty_pages: list[int] = Field(default_factory=list)
    pages_with_substantive_images: list[int] = Field(default_factory=list)
    visual_review_pages: list[int] = Field(
        default_factory=list, description="Union of sparse, empty and substantive-image pages."
    )
    substantive_image_count: int = 0
    decorative_image_count: int = 0
    source_anomalies: list[str] = Field(
        default_factory=list,
        description="Structural oddities observed while reading the source (evidence, not errors).",
    )
    tools: dict[str, str] = Field(
        default_factory=dict, description="Library name -> version used for this manifest."
    )
    generated_at_utc: datetime


# --------------------------------------------------------------------------
# Parsed (Docling) inventory
# --------------------------------------------------------------------------


class PageInventory(_Model):
    """What Docling produced for a single page."""

    page_no: int
    text_items: int = 0
    headings: int = 0
    list_items: int = 0
    tables: int = 0
    pictures: int = 0
    captions: int = 0
    formulas: int = 0
    code_blocks: int = 0
    furniture_items: int = 0
    char_count: int = 0
    word_count: int = 0
    has_provenance: bool = False


class DocumentInventory(_Model):
    """Aggregate structural inventory of the DoclingDocument."""

    page_count: int = 0
    titles: int = 0
    section_headers: int = 0
    headings_by_level: dict[str, int] = Field(default_factory=dict)
    paragraphs: int = 0
    list_items: int = 0
    ordered_list_items: int = 0
    unordered_list_items: int = 0
    tables: int = 0
    table_cells: int = 0
    pictures: int = 0
    captions: int = 0
    formulas: int = 0
    code_blocks: int = 0
    furniture_items: int = 0
    items_with_provenance: int = 0
    items_total: int = 0
    total_char_count: int = 0
    pages: list[PageInventory] = Field(default_factory=list)
    label_counts: dict[str, int] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


class PageCoverage(_Model):
    """Per-page comparison between the independent baseline and Docling output.

    Several metrics are carried on purpose. A single character ratio is easy to
    game: reading-order repair, de-hyphenation and furniture removal all move it
    without any information being lost, and an image-heavy page can score 1.0
    while conveying nothing. The combination is what makes a page reviewable.
    """

    page_no: int
    source_chars: int = 0
    parsed_chars: int = 0
    source_words: int = 0
    parsed_words: int = 0
    furniture_chars_excluded: int = Field(
        default=0,
        description="Characters removed from the NATIVE baseline because preflight proved them to be "
        "repeated header/footer furniture. Excluded from both sides so the comparison is like-for-like; "
        "counting them as loss would flag every page for the page number in its own footer.",
    )
    source_chars_with_furniture: int = 0
    char_coverage: float = Field(default=0.0, description="parsed_chars / source_chars, clipped to [0, 2].")
    token_jaccard: float = 0.0
    token_recall: float = Field(
        default=0.0, description="Fraction of source word types present in parsed text."
    )
    critical_token_recall: float = Field(
        default=1.0, description="Recall over numbers, units and ALL-CAPS acronyms only."
    )
    missing_critical_tokens: list[str] = Field(
        default_factory=list,
        description="Critical tokens absent from this page AND from its neighbours — a candidate true loss.",
    )
    relocated_critical_tokens: list[str] = Field(
        default_factory=list,
        description="Critical tokens absent from this page but present on an adjacent page. Docling "
        "attributes a paragraph spanning a page break to the page where it STARTS, which is correct "
        "reading-order repair, not loss.",
    )
    missing_spans: list[str] = Field(default_factory=list)
    relocated_spans: list[str] = Field(
        default_factory=list, description="Spans found on an adjacent page rather than this one."
    )
    duplicated_spans: list[str] = Field(default_factory=list)
    is_sparse_text: bool = False
    is_image_heavy: bool = False
    has_provenance: bool = False
    pictures: int = 0
    tables: int = 0
    needs_visual_review: bool = False
    review_artifact: str | None = None
    severity: Severity = Severity.INFO
    notes: list[str] = Field(default_factory=list)


class TableFinding(_Model):
    """Per-table audit record, including the named Tables 1/2/3."""

    table_index: int
    self_ref: str
    page_no: int | None = None
    caption: str = ""
    detected_label: str | None = Field(
        default=None, description="e.g. 'Table 1', discovered from caption or nearby text — never hardcoded."
    )
    num_rows: int = 0
    num_cols: int = 0
    num_cells: int = 0
    empty_cell_ratio: float = 0.0
    is_rectangular: bool = True
    has_merged_cells: bool = False
    serialization: Literal["markdown", "html", "asset_only"] = "markdown"
    severity: Severity = Severity.INFO
    notes: list[str] = Field(default_factory=list)


class PictureFinding(_Model):
    """Per-picture audit record distinguishing decorative furniture from substantive diagrams."""

    picture_index: int
    self_ref: str
    page_no: int | None = None
    caption: str = ""
    bbox: tuple[float, float, float, float] | None = None
    area_fraction: float = 0.0
    asset_path: str | None = None
    asset_sha256: str | None = None
    classification: Literal["substantive", "decorative_repeated", "small", "unknown"] = "unknown"
    represents_table_label: str | None = Field(
        default=None,
        description="e.g. 'Table 3' when this picture's caption identifies it as a labelled table whose "
        "body Docling classified as a picture region rather than a table (zero cells, not just zero "
        "recovered cells). Set so the no-silent-loss gate can cover this case too.",
    )
    repeated_on_pages: list[int] = Field(default_factory=list)
    severity: Severity = Severity.INFO
    notes: list[str] = Field(default_factory=list)


class CheckResult(_Model):
    """One validation check with its own severity, evidence and remediation.

    ``gate`` marks the checks that the acceptance criteria treat as blocking.
    """

    check_id: str
    title: str
    passed: bool
    severity: Severity
    gate: bool = Field(default=False, description="True when this check is an acceptance gate.")
    summary: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    threshold: dict[str, Any] = Field(default_factory=dict)
    remediation: str = ""


class ValidationReport(_Model):
    """Aggregated validation outcome written to ``validation/report.json``."""

    status: RunStatus
    strict: bool = False
    generated_at_utc: datetime
    checks: list[CheckResult] = Field(default_factory=list)
    page_coverage: list[PageCoverage] = Field(default_factory=list)
    tables: list[TableFinding] = Field(default_factory=list)
    pictures: list[PictureFinding] = Field(default_factory=list)
    source_inventory: dict[str, Any] = Field(default_factory=dict)
    parsed_inventory: dict[str, Any] = Field(default_factory=dict)
    furniture_removed: list[dict[str, Any]] = Field(default_factory=list)
    human_review_items: list[str] = Field(default_factory=list)

    @property
    def failed_gates(self) -> list[CheckResult]:
        """Blocking checks that did not pass."""
        return [c for c in self.checks if c.gate and not c.passed]

    @property
    def warnings(self) -> list[CheckResult]:
        """Non-blocking checks that did not pass."""
        return [c for c in self.checks if not c.passed and c.severity is Severity.WARNING]

    def compute_status(self, strict: bool) -> RunStatus:
        """Derive the terminal status from the individual checks.

        A critical failure is always ``FAIL``. Warnings are ``FAIL`` in strict
        mode and ``PASS_WITH_WARNINGS`` otherwise.
        """
        if any(not c.passed and c.severity is Severity.CRITICAL for c in self.checks):
            return RunStatus.FAIL
        has_warnings = any(not c.passed and c.severity is Severity.WARNING for c in self.checks)
        if has_warnings:
            return RunStatus.FAIL if strict else RunStatus.PASS_WITH_WARNINGS
        return RunStatus.PASS

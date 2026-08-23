"""Validated, hashable configuration for the parser.

Configuration is a *public contract* deliberately decoupled from Docling's own
option classes. Callers write stable keys like ``docling.table_mode``;
:mod:`engineering_rag_parser.pipeline_factory` is the only place that translates
those into the installed Docling types. That keeps Docling API churn out of
user-facing YAML and out of stored run manifests.

Every effective configuration is hashed (:meth:`ParserConfig.config_hash`) and
written into the run manifest so a run can be tied to the exact settings that
produced it.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "AcceleratorDeviceName",
    "DoclingOptions",
    "ExportOptions",
    "LimitsOptions",
    "ParserConfig",
    "PictureDescriptionOptions",
    "Profile",
    "ValidationThresholds",
    "load_config",
]


class Profile(str, Enum):
    """Named conversion strategies. See ``configs/*.yaml`` for the shipped set."""

    DEFAULT = "default"
    HIGH_FIDELITY = "high_fidelity"
    SCANNED = "scanned"
    AUTO = "auto"


class AcceleratorDeviceName(str, Enum):
    """Mirrors ``docling.datamodel.pipeline_options.AcceleratorDevice`` values.

    Kept as an independent enum so that a Docling upgrade adding or removing a
    device cannot silently change the meaning of a stored config hash.
    """

    AUTO = "auto"
    CPU = "cpu"
    CUDA = "cuda"
    MPS = "mps"
    XPU = "xpu"


class _Frozen(BaseModel):
    """Immutable, strict base: an unknown key is a configuration error, not a typo we ignore."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class LimitsOptions(_Frozen):
    """Resource and safety limits.

    The source PDF is treated as untrusted input: never uploaded, never
    executed, and bounded in size/pages/time so a malformed or hostile file
    cannot exhaust the host.
    """

    max_file_size_mb: float = Field(default=256.0, gt=0, description="Reject inputs larger than this.")
    max_pages: int = Field(default=2000, gt=0, description="Reject inputs with more pages than this.")
    document_timeout_s: float | None = Field(
        default=3600.0, gt=0, description="Wall-clock ceiling handed to Docling; None disables."
    )
    max_render_pages: int = Field(default=200, gt=0, description="Upper bound on preflight page rasterisations.")


class PictureDescriptionOptions(_Frozen):
    """Optional local VLM picture description.

    Disabled by default on purpose (ADR-005): a generated caption for a P&ID or
    a loop wiring diagram is exactly where a plausible-sounding hallucination is
    most damaging. When enabled, output is labelled machine-generated and never
    replaces the picture asset or its provenance.
    """

    enabled: bool = False
    repo_id: str = Field(
        default="HuggingFaceTB/SmolVLM-256M-Instruct",
        description="HF repo for the local VLM. Never contacted while enabled=False.",
    )
    prompt: str = Field(
        default=(
            "Describe only what is literally visible in this engineering figure: "
            "shapes, visible labels, and connections. Do not infer function or intent."
        )
    )
    picture_area_threshold: float = Field(
        default=0.05, ge=0.0, le=1.0, description="Skip pictures covering less than this fraction of the page."
    )
    batch_size: int = Field(default=4, gt=0)
    require_gpu_vram_mb: int = Field(
        default=4096,
        ge=0,
        description="Refuse to auto-enable on a GPU smaller than this; forces an explicit override.",
    )


class DoclingOptions(_Frozen):
    """Public keys mapped onto the installed Docling option classes.

    Note on ``do_ocr``: Docling 2.121.0 ships ``do_ocr=True`` by default. For a
    digitally generated, text-searchable PDF that is actively harmful — OCR can
    duplicate or degrade clean embedded text — so this project defaults it to
    ``False`` and enables it only from preflight evidence.
    """

    backend: Literal["dlparse_v4", "dlparse_v2", "docling_parse", "pypdfium2"] = "dlparse_v4"
    do_ocr: bool = False
    ocr_engine: Literal["auto", "easyocr", "rapidocr", "tesseract", "tesseract_cli", "ocrmac"] = "easyocr"
    ocr_languages: tuple[str, ...] = ("en",)
    ocr_force_full_page: bool = False
    ocr_mode: Literal["default", "full_page", "layout_regions", "pdf_aware_layout_regions"] = "default"

    do_table_structure: bool = True
    table_mode: Literal["fast", "accurate"] = "accurate"
    table_cell_matching: bool = True

    generate_page_images: bool = True
    generate_picture_images: bool = True
    generate_table_images: bool = False
    images_scale: float = Field(default=2.0, gt=0, le=8.0)

    do_picture_classification: bool = False
    do_code_enrichment: bool = False
    do_formula_enrichment: bool = False
    enable_heading_hierarchy: bool = True

    accelerator_device: AcceleratorDeviceName = AcceleratorDeviceName.CPU
    num_threads: int = Field(default=4, gt=0, le=64)

    artifacts_path: Path | None = Field(
        default=None, description="Local Docling model cache. Set for fully offline operation."
    )
    enable_remote_services: bool = Field(
        default=False, description="Must stay False: this project is local-only by policy."
    )
    allow_external_plugins: bool = False

    picture_description: PictureDescriptionOptions = PictureDescriptionOptions()

    @field_validator("enable_remote_services")
    @classmethod
    def _forbid_remote(cls, v: bool) -> bool:
        if v:
            raise ValueError(
                "enable_remote_services must remain False: the source document is treated as "
                "confidential and must never leave the machine."
            )
        return v

    @field_validator("ocr_languages", mode="before")
    @classmethod
    def _coerce_langs(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v


class ExportOptions(_Frozen):
    """Markdown/asset export and deterministic post-processing switches."""

    emit_page_anchors: bool = Field(
        default=True, description="Insert unobtrusive HTML page-provenance comments for future RAG citation."
    )
    page_anchor_template: str = "<!-- page: {page_no} -->"
    strip_furniture: bool = Field(
        default=True, description="Export ContentLayer.BODY only; furniture is kept in the audit copy."
    )
    remove_repeated_furniture_text: bool = Field(
        default=True,
        description="Additionally drop body lines that preflight proved are repeated header/footer furniture.",
    )
    furniture_min_page_fraction: float = Field(
        default=0.5, ge=0.0, le=1.0, description="A line must repeat on >= this fraction of pages to be furniture."
    )
    complex_table_as_html: bool = Field(
        default=True, description="Merged/ragged tables become HTML rather than a lossy Markdown flattening."
    )
    image_subdir: str = "assets/pictures"
    page_image_subdir: str = "assets/pages"
    save_page_images: bool = True
    keep_raw_serializer_output: bool = Field(
        default=True, description="Always retain the untouched Docling Markdown as an audit artifact."
    )
    escape_underscores: bool = Field(
        default=False,
        description="Docling defaults to True; underscores are common in engineering tag names (FT_101) "
        "and escaping them corrupts the token for downstream retrieval.",
    )


class ValidationThresholds(_Frozen):
    """Thresholds for the coverage checks.

    Deliberately explicit and configurable rather than magic numbers buried in
    the checkers: a threshold is a *policy* decision a reviewing engineer must
    be able to see and challenge.
    """

    sparse_text_char_threshold: int = Field(
        default=200, ge=0, description="Pages with fewer native chars are 'sparse' and need visual review."
    )
    image_heavy_area_fraction: float = Field(
        default=0.25, ge=0.0, le=1.0, description="Image coverage above this makes a page 'image-heavy'."
    )
    page_char_coverage_warn: float = Field(default=0.80, ge=0.0, le=1.0)
    page_char_coverage_fail: float = Field(default=0.50, ge=0.0, le=1.0)
    page_token_jaccard_warn: float = Field(default=0.70, ge=0.0, le=1.0)
    page_token_recall_warn: float = Field(
        default=0.85, ge=0.0, le=1.0, description="Fraction of native word types that must survive into Docling text."
    )
    critical_token_recall_fail: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Numbers/units/acronyms are high-information; losing them is a critical defect.",
    )
    max_empty_table_cell_ratio: float = Field(default=0.50, ge=0.0, le=1.0)
    min_pages_with_provenance: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ordering(self) -> ValidationThresholds:
        if self.page_char_coverage_fail > self.page_char_coverage_warn:
            raise ValueError("page_char_coverage_fail must be <= page_char_coverage_warn")
        return self


class ParserConfig(_Frozen):
    """Top-level, hashable parser configuration."""

    profile: Profile = Profile.DEFAULT
    docling: DoclingOptions = DoclingOptions()
    export: ExportOptions = ExportOptions()
    limits: LimitsOptions = LimitsOptions()
    thresholds: ValidationThresholds = ValidationThresholds()

    redact_text_samples: bool = Field(default=True, description="Truncate any source text echoed into logs/reports.")
    text_sample_chars: int = Field(default=160, ge=0, le=2000)
    strict: bool = Field(default=False, description="Treat warnings as failures (CI gate).")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    def effective_dict(self) -> dict[str, Any]:
        """JSON-safe view of the effective configuration, suitable for a manifest."""
        return json.loads(self.model_dump_json())

    def config_hash(self) -> str:
        """Stable SHA-256 over the effective configuration.

        Sorted keys and compact separators make the hash independent of field
        declaration order, so re-ordering the model does not invalidate history.
        """
        payload = json.dumps(self.effective_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def with_overrides(self, **overrides: Any) -> ParserConfig:
        """Return a new config with top-level fields replaced (frozen-model friendly)."""
        return self.model_copy(update=overrides)


def load_config(path: Path | str | None = None, **overrides: Any) -> ParserConfig:
    """Load a YAML config file, applying top-level overrides.

    A missing ``path`` yields the built-in defaults, so the package is usable
    with no configuration at all.

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
            raise ValueError(f"Config file must contain a YAML mapping, got {type(loaded).__name__}: {cfg_path}")
        data = loaded
    data.update({k: v for k, v in overrides.items() if v is not None})
    return ParserConfig.model_validate(data)

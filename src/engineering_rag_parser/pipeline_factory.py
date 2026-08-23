"""The only module that constructs Docling objects.

Every Docling import in the runtime path lives here. When Docling changes an
option name, moves a backend or deprecates an enum, exactly one file needs
editing and the public YAML contract in :mod:`engineering_rag_parser.config`
stays put.

Findings from introspecting the installed docling 2.121.0 that shaped this code:

* ``PdfPipelineOptions.do_ocr`` defaults to **True**. For a digitally generated,
  text-searchable PDF that is harmful, so the profiles here set it explicitly
  rather than inheriting the default.
* ``DoclingParseV4DocumentBackend`` is a deprecation shim that raises a
  ``FutureWarning`` and is documented as removed in 2.74.0; ``PdfBackend``
  normalises ``DLPARSE_V1/V2/V4`` back to ``DOCLING_PARSE``. The current class is
  ``DoclingParseDocumentBackend``.
* ``TableStructureOptions`` already defaults to ``TableFormerMode.ACCURATE``.
* ``PdfPipelineOptions.heading_hierarchy_options.enabled`` defaults to False;
  enabling it improves section nesting on a numbered engineering document.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from docling.backend.docling_parse_backend import DoclingParseDocumentBackend
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    AcceleratorDevice,
    AcceleratorOptions,
    EasyOcrOptions,
    HeadingHierarchyOptions,
    OcrOptions,
    PdfPipelineOptions,
    RapidOcrOptions,
    TableFormerMode,
    TableStructureOptions,
    TesseractCliOcrOptions,
    TesseractOcrOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption

from .config import AcceleratorDeviceName, DoclingOptions, ParserConfig, Profile
from .domain import SourceManifest

__all__ = [
    "ProfileDecision",
    "build_converter",
    "build_pipeline_options",
    "choose_profile",
    "describe_effective_options",
    "docling_versions",
    "resolve_profile_config",
]

logger = logging.getLogger(__name__)

_BACKENDS: dict[str, type] = {
    "docling_parse": DoclingParseDocumentBackend,
    "pypdfium2": PyPdfiumDocumentBackend,
}
try:  # Present in some builds only; degrade to the standard backend if absent.
    from docling.backend.docling_parse_backend import ThreadedDoclingParseDocumentBackend

    _BACKENDS["threaded_docling_parse"] = ThreadedDoclingParseDocumentBackend
except ImportError:  # pragma: no cover - depends on the installed build
    logger.debug("ThreadedDoclingParseDocumentBackend unavailable in this docling build.")

_OCR_ENGINES: dict[str, type[OcrOptions]] = {
    "easyocr": EasyOcrOptions,
    "rapidocr": RapidOcrOptions,
    "tesseract": TesseractOcrOptions,
    "tesseract_cli": TesseractCliOcrOptions,
}

_DEVICES: dict[AcceleratorDeviceName, AcceleratorDevice] = {
    AcceleratorDeviceName.AUTO: AcceleratorDevice.AUTO,
    AcceleratorDeviceName.CPU: AcceleratorDevice.CPU,
    AcceleratorDeviceName.CUDA: AcceleratorDevice.CUDA,
    AcceleratorDeviceName.MPS: AcceleratorDevice.MPS,
    AcceleratorDeviceName.XPU: AcceleratorDevice.XPU,
}


@dataclass(frozen=True)
class ProfileDecision:
    """A profile choice plus the evidence that justified it.

    Auditability is the point: a run manifest that says "profile: scanned" is
    useless six months later without the measurement that caused it.
    """

    profile: Profile
    reason: str
    evidence: dict[str, Any]


def docling_versions() -> dict[str, str]:
    """Versions of the Docling stack actually installed in this environment.

    Read from installed distribution metadata rather than ``module.__version__``:
    several of these packages do not define that attribute, and a manifest that
    records ``"unknown"`` for the table-structure model package is not
    reproducible evidence.
    """
    from importlib.metadata import PackageNotFoundError, version

    versions: dict[str, str] = {}
    for dist in ("docling", "docling-core", "docling-ibm-models", "docling-parse", "torch", "torchvision"):
        try:
            versions[dist] = version(dist)
        except PackageNotFoundError:
            versions[dist] = "not-installed"
    try:
        import torch

        versions["torch_cuda_available"] = str(torch.cuda.is_available())
        versions["torch_cuda_device_count"] = str(torch.cuda.device_count() if torch.cuda.is_available() else 0)
    except Exception:  # noqa: BLE001
        versions["torch_cuda_available"] = "unknown"
    return versions


def choose_profile(manifest: SourceManifest, config: ParserConfig) -> ProfileDecision:
    """Decide the effective profile for ``auto``, or confirm an explicit choice.

    The rule is deliberately conservative. OCR is enabled only when the document
    genuinely lacks an extractable text layer, because running OCR over good
    embedded text duplicates and degrades it — the exact failure this project
    must avoid.
    """
    pages = manifest.page_count or 1
    empty_or_sparse = len(set(manifest.sparse_pages) | set(manifest.empty_pages))
    sparse_fraction = empty_or_sparse / pages
    chars_per_page = manifest.total_char_count / pages
    evidence = {
        "page_count": pages,
        "total_char_count": manifest.total_char_count,
        "chars_per_page": round(chars_per_page, 1),
        "sparse_or_empty_pages": sorted(set(manifest.sparse_pages) | set(manifest.empty_pages)),
        "sparse_fraction": round(sparse_fraction, 4),
        "substantive_image_count": manifest.substantive_image_count,
    }

    if config.profile is not Profile.AUTO:
        return ProfileDecision(
            profile=config.profile,
            reason=f"Profile '{config.profile.value}' was requested explicitly; preflight evidence recorded for audit.",
            evidence=evidence,
        )

    # A genuinely scanned document has almost no extractable text anywhere.
    if sparse_fraction >= 0.8 or chars_per_page < 50:
        return ProfileDecision(
            profile=Profile.SCANNED,
            reason=(
                f"{empty_or_sparse}/{pages} pages carry little or no extractable text "
                f"({chars_per_page:.0f} chars/page): the document behaves as image-only, so OCR is required."
            ),
            evidence=evidence,
        )
    if manifest.substantive_image_count > 0:
        return ProfileDecision(
            profile=Profile.HIGH_FIDELITY,
            reason=(
                f"Native text is present ({chars_per_page:.0f} chars/page) and {manifest.substantive_image_count} "
                "non-repeated figure(s) were found: use accurate tables and referenced picture assets, without OCR."
            ),
            evidence=evidence,
        )
    return ProfileDecision(
        profile=Profile.DEFAULT,
        reason=f"Uniform digital text ({chars_per_page:.0f} chars/page) with no substantive figures; CPU-safe defaults suffice.",
        evidence=evidence,
    )


def resolve_profile_config(config: ParserConfig, profile: Profile) -> ParserConfig:
    """Apply a named profile's option overrides onto ``config``.

    Only Docling-facing options are touched; user-set thresholds, limits and
    export settings are preserved so a profile cannot silently relax a gate.
    """
    docling_opts = config.docling
    if profile is Profile.HIGH_FIDELITY:
        docling_opts = docling_opts.model_copy(
            update={
                "do_ocr": False,
                "do_table_structure": True,
                "table_mode": "accurate",
                "table_cell_matching": True,
                "generate_page_images": True,
                "generate_picture_images": True,
                "images_scale": max(docling_opts.images_scale, 2.0),
                "enable_heading_hierarchy": True,
            }
        )
    elif profile is Profile.SCANNED:
        docling_opts = docling_opts.model_copy(
            update={
                "do_ocr": True,
                "ocr_force_full_page": True,
                "ocr_mode": "full_page",
                "do_table_structure": True,
                "table_mode": "accurate",
                "generate_page_images": True,
                "generate_picture_images": True,
            }
        )
    elif profile is Profile.DEFAULT:
        docling_opts = docling_opts.model_copy(
            update={
                "do_ocr": False,
                "table_mode": "fast",
                "images_scale": min(docling_opts.images_scale, 1.5),
            }
        )
    return config.model_copy(update={"profile": profile, "docling": docling_opts})


def _build_ocr_options(opts: DoclingOptions) -> OcrOptions:
    """Construct the OCR options object for the selected engine."""
    engine_cls = _OCR_ENGINES.get(opts.ocr_engine)
    if engine_cls is None:
        # 'auto' and 'ocrmac' have no directly constructible class in this build.
        logger.info("OCR engine %r has no explicit options class; using EasyOCR options.", opts.ocr_engine)
        engine_cls = EasyOcrOptions
    kwargs: dict[str, Any] = {"lang": list(opts.ocr_languages)}
    # `force_full_page_ocr` is deprecated in docling 2.121.0 in favour of
    # `mode=OcrMode.FULL_PAGE`; prefer the current field and fall back only if a
    # build lacks it.
    if "mode" in engine_cls.model_fields:
        kwargs["mode"] = "full_page" if opts.ocr_force_full_page else opts.ocr_mode
    else:
        kwargs["force_full_page_ocr"] = opts.ocr_force_full_page
    if "download_enabled" in engine_cls.model_fields:
        # Model weights must already be cached for the offline path to hold.
        kwargs["download_enabled"] = True
    return engine_cls(**kwargs)


def build_pipeline_options(config: ParserConfig) -> PdfPipelineOptions:
    """Translate :class:`ParserConfig` into installed Docling pipeline options."""
    opts = config.docling
    pipeline = PdfPipelineOptions()

    pipeline.do_ocr = opts.do_ocr
    if opts.do_ocr:
        pipeline.ocr_options = _build_ocr_options(opts)

    pipeline.do_table_structure = opts.do_table_structure
    pipeline.table_structure_options = TableStructureOptions(
        do_cell_matching=opts.table_cell_matching,
        mode=TableFormerMode.ACCURATE if opts.table_mode == "accurate" else TableFormerMode.FAST,
    )

    pipeline.generate_page_images = opts.generate_page_images
    pipeline.generate_picture_images = opts.generate_picture_images
    pipeline.generate_table_images = opts.generate_table_images
    pipeline.images_scale = opts.images_scale

    pipeline.do_picture_classification = opts.do_picture_classification
    pipeline.do_code_enrichment = opts.do_code_enrichment
    pipeline.do_formula_enrichment = opts.do_formula_enrichment

    if "heading_hierarchy_options" in PdfPipelineOptions.model_fields:
        pipeline.heading_hierarchy_options = HeadingHierarchyOptions(enabled=opts.enable_heading_hierarchy)

    pipeline.accelerator_options = AcceleratorOptions(
        num_threads=opts.num_threads,
        device=_DEVICES[opts.accelerator_device],
    )

    pipeline.enable_remote_services = False  # policy, not preference
    pipeline.allow_external_plugins = opts.allow_external_plugins
    if opts.artifacts_path is not None:
        pipeline.artifacts_path = opts.artifacts_path
    if config.limits.document_timeout_s is not None:
        pipeline.document_timeout = float(config.limits.document_timeout_s)

    pipeline.do_picture_description = opts.picture_description.enabled
    if opts.picture_description.enabled:
        _configure_picture_description(pipeline, opts)

    return pipeline


def _configure_picture_description(pipeline: PdfPipelineOptions, opts: DoclingOptions) -> None:
    """Attach local-VLM picture description options (opt-in only).

    Guarded by an import check so that a build without the VLM options class
    fails loudly at configuration time rather than silently producing a document
    with no descriptions while the manifest claims otherwise.
    """
    try:
        from docling.datamodel.pipeline_options import PictureDescriptionVlmOptions
    except ImportError as exc:  # pragma: no cover - depends on installed build
        raise RuntimeError(
            "picture_description.enabled=true but this docling build exposes no "
            "PictureDescriptionVlmOptions; disable the option or install a build that supports it."
        ) from exc
    pd = opts.picture_description
    pipeline.picture_description_options = PictureDescriptionVlmOptions(
        repo_id=pd.repo_id,
        prompt=pd.prompt,
        picture_area_threshold=pd.picture_area_threshold,
        batch_size=pd.batch_size,
    )
    logger.warning(
        "Local VLM picture description is ENABLED (%s). Generated text is a machine annotation, "
        "is not evidence that diagram labels or relationships were recovered, and must be reviewed.",
        pd.repo_id,
    )


def build_converter(config: ParserConfig) -> DocumentConverter:
    """Build a :class:`DocumentConverter` restricted to PDF input.

    Restricting ``allowed_formats`` to PDF is a safety measure: the input is
    untrusted, and there is no reason for this pipeline to accept the dozens of
    other formats Docling can open.
    """
    backend_cls = _BACKENDS.get(config.docling.backend)
    if backend_cls is None:
        available = ", ".join(sorted(_BACKENDS))
        raise ValueError(f"Unknown PDF backend {config.docling.backend!r}. Available: {available}")

    pipeline_options = build_pipeline_options(config)
    logger.info(
        "Docling converter: backend=%s do_ocr=%s table_mode=%s device=%s scale=%.1f",
        config.docling.backend, config.docling.do_ocr, config.docling.table_mode,
        config.docling.accelerator_device.value, config.docling.images_scale,
    )
    return DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options, backend=backend_cls)
        },
    )


def describe_effective_options(config: ParserConfig) -> dict[str, Any]:
    """Serialise the *actual* Docling options for the run manifest and the docs.

    Generated by dumping the constructed object rather than by hand, so the
    parameter guide cannot drift away from what the code really does.
    """
    pipeline = build_pipeline_options(config)
    return {
        "backend_class": _BACKENDS[config.docling.backend].__name__,
        "pipeline_class": "StandardPdfPipeline",
        "pipeline_options": pipeline.model_dump(mode="json"),
        "versions": docling_versions(),
    }

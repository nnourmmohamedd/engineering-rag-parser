"""The only module that constructs Docling objects, runs a conversion, and
owns the resulting :class:`~docling_core.types.doc.DoclingDocument`'s lifecycle.

Every Docling import in the runtime path lives here (plus ``exporters.py`` and
``validation/structure.py``/``validation/visual.py``, which read the resulting
document). When Docling changes an option name, moves a backend or deprecates
an enum, this is the module that absorbs it — the public YAML contract in
:mod:`engineering_rag.services.parser.config` stays put.

This module used to be two files (``pipeline_factory.py`` for object
construction, ``parser.py`` for conversion + serialisation); they are merged
here because both halves are "own the Docling converter and its document",
one responsibility. Profile *selection* (deciding which strategy to use) is a
separate concern and lives in :mod:`engineering_rag.services.parser.profiles`.
Structural *counting* of the resulting document is a separate concern and
lives in :mod:`engineering_rag.services.parser.inventory`.

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

The contract around conversion failure is deliberately blunt. A conversion
that returns no document, or returns a partial one, must never produce
artifacts that look like a healthy run.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docling.backend.docling_parse_backend import DoclingParseDocumentBackend
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.document import ConversionResult
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
from docling_core.types.doc import ContentLayer, DoclingDocument, ImageRefMode, TableItem

from .config import AcceleratorDeviceName, DoclingOptions, ParserConfig

__all__ = [
    "ConversionFailedError",
    "ConversionOutcome",
    "build_converter",
    "build_pipeline_options",
    "convert_pdf",
    "describe_effective_options",
    "docling_versions",
    "page_texts",
    "reload_document_json",
    "save_document_json",
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
        versions["torch_cuda_device_count"] = str(
            torch.cuda.device_count() if torch.cuda.is_available() else 0
        )
    except Exception:  # noqa: BLE001
        versions["torch_cuda_available"] = "unknown"
    return versions


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
        config.docling.backend,
        config.docling.do_ocr,
        config.docling.table_mode,
        config.docling.accelerator_device.value,
        config.docling.images_scale,
    )
    return DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options, backend=backend_cls)
        },
    )


def _describe_suboption(obj: Any) -> dict[str, Any] | None:
    """Dump a nested Docling option object by its *concrete* runtime class.

    ``PdfPipelineOptions.model_dump()`` serialises nested option fields (table
    structure, OCR engine, picture description) using the field's *declared*
    type annotation, which for several of these fields is an abstract base
    class with no fields of its own — the concrete subclass fields are
    silently dropped and the manifest records ``{}`` even though the runtime
    object is fully configured (see audit finding D-2). Dumping
    ``type(obj).__name__`` plus ``obj.model_dump()`` on the object directly
    (rather than through the parent's field type) recovers the real values.
    """
    if obj is None:
        return None
    dumped = obj.model_dump(mode="json") if hasattr(obj, "model_dump") else {}
    return {"type": type(obj).__name__, **dumped}


def describe_effective_options(config: ParserConfig) -> dict[str, Any]:
    """Serialise the *actual* Docling options for the run manifest and the docs.

    Generated by dumping the constructed object rather than by hand, so the
    parameter guide cannot drift away from what the code really does. Fields
    typed as an abstract base class on ``PdfPipelineOptions`` (table structure,
    OCR, picture description) are re-serialised from the live object by
    ``_describe_suboption`` so the concrete, effective values are recorded
    instead of an empty ``{}`` (D-2).
    """
    pipeline = build_pipeline_options(config)
    dumped = pipeline.model_dump(mode="json")
    dumped["table_structure_options"] = _describe_suboption(pipeline.table_structure_options)
    dumped["ocr_options"] = _describe_suboption(pipeline.ocr_options)
    dumped["picture_description_options"] = _describe_suboption(
        getattr(pipeline, "picture_description_options", None)
    )
    return {
        "backend_class": _BACKENDS[config.docling.backend].__name__,
        "pipeline_class": "StandardPdfPipeline",
        "pipeline_options": dumped,
        "versions": docling_versions(),
    }


class ConversionFailedError(RuntimeError):
    """Raised when Docling returns no usable document."""


@dataclass
class ConversionOutcome:
    """Result of a Docling conversion plus the evidence about how it went."""

    document: DoclingDocument
    status: str
    is_partial: bool
    errors: list[dict[str, Any]] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    confidence: dict[str, Any] = field(default_factory=dict)
    page_count: int = 0
    wall_time_s: float = 0.0


def _extract_errors(result: ConversionResult) -> list[dict[str, Any]]:
    """Normalise Docling's error items into plain dictionaries."""
    errors: list[dict[str, Any]] = []
    for err in getattr(result, "errors", []) or []:
        if hasattr(err, "model_dump"):
            errors.append(err.model_dump(mode="json"))
        else:
            errors.append({"error": str(err)})
    return errors


def _extract_timings(result: ConversionResult) -> dict[str, float]:
    """Pull per-stage timings out of the conversion result, if the build exposes them."""
    timings: dict[str, float] = {}
    raw = getattr(result, "timings", None) or {}
    for key, item in raw.items():
        try:
            times = getattr(item, "times", None)
            if times:
                timings[str(key)] = round(float(sum(times)), 4)
            elif hasattr(item, "count"):
                timings[str(key)] = 0.0
        except Exception:  # noqa: BLE001 - telemetry must never break a run
            logger.debug("Could not read timing for stage %s", key)
    return timings


def _extract_confidence(result: ConversionResult) -> dict[str, Any]:
    """Pull Docling's confidence report, which varies by build."""
    conf = getattr(result, "confidence", None)
    if conf is None:
        return {}
    try:
        if hasattr(conf, "model_dump"):
            return conf.model_dump(mode="json")
        return {"value": float(conf)}
    except Exception:  # noqa: BLE001
        return {"repr": str(conf)[:500]}


def convert_pdf(pdf_path: Path, config: ParserConfig) -> ConversionOutcome:
    """Convert a PDF with Docling and capture the full result envelope.

    ``raises_on_error=False`` is used deliberately so that a partial conversion
    is *observable* — the alternative is an exception that discards the evidence
    about which pages did succeed.

    Raises:
        ConversionFailedError: if no document is returned, or the document has
            no pages.
    """
    converter = build_converter(config)
    logger.info("Converting %s with Docling…", pdf_path.name)
    started = time.perf_counter()
    result = converter.convert(
        pdf_path,
        raises_on_error=False,
        max_num_pages=config.limits.max_pages,
        max_file_size=int(config.limits.max_file_size_mb * 1024 * 1024),
    )
    wall = time.perf_counter() - started

    status = result.status
    errors = _extract_errors(result)
    document = getattr(result, "document", None)

    if status in (ConversionStatus.FAILURE, ConversionStatus.SKIPPED) or document is None:
        raise ConversionFailedError(
            f"Docling returned status={getattr(status, 'value', status)} with no usable document "
            f"after {wall:.1f}s. Errors: {errors[:3]}"
        )
    if not document.pages:
        raise ConversionFailedError(
            f"Docling returned a document with zero pages (status={getattr(status, 'value', status)}); "
            "refusing to emit artifacts for an empty parse."
        )

    is_partial = status == ConversionStatus.PARTIAL_SUCCESS
    if is_partial:
        logger.error(
            "Docling reported PARTIAL_SUCCESS: %d error item(s). Artifacts will be quarantined.", len(errors)
        )

    outcome = ConversionOutcome(
        document=document,
        status=getattr(status, "value", str(status)),
        is_partial=is_partial,
        errors=errors,
        timings=_extract_timings(result),
        confidence=_extract_confidence(result),
        page_count=len(document.pages),
        wall_time_s=round(wall, 3),
    )
    logger.info(
        "Conversion %s in %.1fs: %d pages, %d texts, %d tables, %d pictures",
        outcome.status,
        wall,
        outcome.page_count,
        len(document.texts),
        len(document.tables),
        len(document.pictures),
    )
    return outcome


#: Asset directory for the canonical JSON, as a **relative** name.
#: ``DoclingDocument._get_output_paths`` joins a relative ``artifacts_dir`` onto
#: ``filename.parent`` and then writes *relative* image URIs into the JSON. An
#: absolute path would be used verbatim and would bake this machine's directory
#: layout into a portable artifact, so a bare relative name is required here.
_JSON_ASSET_DIRNAME = "assets"

#: Matches a JSON string value under a ``"uri"`` key, honouring JSON's own
#: backslash-escaping (``\\`` for a literal backslash, ``\"`` for a quote)
#: so the match stops at the real closing quote rather than an escaped one.
_URI_FIELD_RE = re.compile(r'("uri"\s*:\s*")((?:[^"\\]|\\.)*)(")')


def _portabalize_json_uris(text: str) -> str:
    """Rewrite Windows-backslash path separators in JSON ``"uri"`` values to ``/``.

    Docling's own serialiser writes the OS-native separator for the local
    relative asset paths it emits (``ImageRefMode.REFERENCED``). On Windows
    that means literal ``\\`` inside the JSON string, which is not a path
    separator on POSIX — the artifact would not resolve on Linux/macOS
    (audit finding D-3). Remote ``http(s)``/``data:`` URIs never contain a
    backslash and are left untouched by construction.
    """

    def _fix(match: re.Match[str]) -> str:
        prefix, value, suffix = match.group(1), match.group(2), match.group(3)
        if "\\\\" not in value:
            return match.group(0)
        return f"{prefix}{value.replace(chr(92) * 2, '/')}{suffix}"

    return _URI_FIELD_RE.sub(_fix, text)


def save_document_json(document: DoclingDocument, dest: Path) -> Path:
    """Serialise the DoclingDocument with Docling's own serialiser.

    Uses ``ImageRefMode.REFERENCED`` rather than the ``EMBEDDED`` default: a
    base64 payload per picture would bloat the JSON into the tens of megabytes
    and make diffing a run impossible. Assets are written to
    ``<dest.parent>/assets/`` and referenced by relative URI.

    The file is post-processed to normalise any Windows path separator inside
    a ``"uri"`` value to a portable forward slash (D-3), then re-validated by
    reloading it back through the DoclingDocument model so a broken rewrite
    can never be shipped silently.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    document.save_as_json(
        dest,
        artifacts_dir=Path(_JSON_ASSET_DIRNAME),
        image_mode=ImageRefMode.REFERENCED,
        indent=2,
    )
    original = dest.read_text(encoding="utf-8")
    portable = _portabalize_json_uris(original)
    if portable != original:
        dest.write_text(portable, encoding="utf-8", newline="\n")
        DoclingDocument.load_from_json(dest)  # fail loudly if the rewrite broke the JSON
    return dest


def reload_document_json(path: Path) -> DoclingDocument:
    """Reload a serialised document through the current DoclingDocument model.

    This is the round-trip gate: if the file we wrote cannot be validated back
    into the model, the artifact is not a usable handoff to the next stage.
    """
    return DoclingDocument.load_from_json(path)


def page_texts(document: DoclingDocument, *, body_only: bool = True) -> dict[int, str]:
    """Collect Docling's text per page for the coverage comparison.

    Table cell text is included: a table's contents are real page content, and
    excluding them would make every table page look like catastrophic text loss.
    """
    layers = (
        {ContentLayer.BODY}
        if body_only
        else {ContentLayer.BODY, ContentLayer.FURNITURE, ContentLayer.BACKGROUND}
    )
    buckets: dict[int, list[str]] = {int(no): [] for no in document.pages}

    for item, _level in document.iterate_items(with_groups=False, included_content_layers=layers):
        provs = list(getattr(item, "prov", []) or [])
        if not provs:
            continue
        page_no = int(provs[0].page_no)
        if page_no not in buckets:
            buckets[page_no] = []

        if isinstance(item, TableItem):
            data = getattr(item, "data", None)
            for cell in getattr(data, "table_cells", []) or []:
                cell_text = getattr(cell, "text", "") or ""
                if cell_text:
                    buckets[page_no].append(cell_text)
            continue

        text = getattr(item, "text", "") or ""
        if text:
            buckets[page_no].append(text)

    return {page: "\n".join(parts) for page, parts in buckets.items()}

"""Docling conversion, conversion-result handling and canonical serialisation.

The contract of this module is deliberately blunt about failure. A conversion
that returns no document, or returns a partial one, must never produce artifacts
that look like a healthy run — partial output is routed to a quarantine
directory and the run is marked ``FAIL``.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docling.datamodel.base_models import ConversionStatus
from docling.datamodel.document import ConversionResult
from docling_core.types.doc import (
    ContentLayer,
    DocItemLabel,
    DoclingDocument,
    ImageRefMode,
    PictureItem,
    SectionHeaderItem,
    TableItem,
    TextItem,
)

from .config import ParserConfig
from .domain import DocumentInventory, PageInventory
from .pipeline_factory import build_converter

__all__ = [
    "ConversionOutcome",
    "ConversionFailedError",
    "build_inventory",
    "convert_pdf",
    "save_document_json",
]

logger = logging.getLogger(__name__)

_HEADING_LABELS = {DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER}
_LIST_LABELS = {DocItemLabel.LIST_ITEM}
_FURNITURE_LABELS = {DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER}


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


def build_inventory(document: DoclingDocument) -> DocumentInventory:
    """Walk the document once and count everything the validators need.

    Furniture (``ContentLayer.FURNITURE``) is counted separately rather than
    skipped, because "what did we classify as furniture" is itself audit
    evidence that the report has to show.
    """
    inv = DocumentInventory(page_count=len(document.pages))
    pages: dict[int, PageInventory] = {int(no): PageInventory(page_no=int(no)) for no in document.pages}
    label_counts: Counter[str] = Counter()
    headings_by_level: Counter[str] = Counter()

    all_layers = {ContentLayer.BODY, ContentLayer.FURNITURE, ContentLayer.BACKGROUND}
    for item, _level in document.iterate_items(with_groups=False, included_content_layers=all_layers):
        label = getattr(item, "label", None)
        label_name = getattr(label, "value", str(label)) if label is not None else "unknown"
        label_counts[label_name] += 1
        inv.items_total += 1

        provs = list(getattr(item, "prov", []) or [])
        if provs:
            inv.items_with_provenance += 1
        page_no = int(provs[0].page_no) if provs else None
        page_inv = pages.get(page_no) if page_no is not None else None
        if page_inv is not None:
            page_inv.has_provenance = True

        is_furniture = getattr(item, "content_layer", None) == ContentLayer.FURNITURE
        if is_furniture:
            inv.furniture_items += 1
            if page_inv:
                page_inv.furniture_items += 1

        if isinstance(item, TableItem):
            inv.tables += 1
            data = getattr(item, "data", None)
            if data is not None:
                inv.table_cells += len(getattr(data, "table_cells", []) or [])
            if page_inv:
                page_inv.tables += 1
            continue

        if isinstance(item, PictureItem):
            inv.pictures += 1
            if page_inv:
                page_inv.pictures += 1
            continue

        text = getattr(item, "text", "") or ""
        inv.total_char_count += len(text)
        if page_inv:
            page_inv.char_count += len(text)
            page_inv.word_count += len(text.split())
            page_inv.text_items += 1

        if label == DocItemLabel.TITLE:
            inv.titles += 1
            headings_by_level["title"] += 1
            if page_inv:
                page_inv.headings += 1
        elif isinstance(item, SectionHeaderItem) or label == DocItemLabel.SECTION_HEADER:
            inv.section_headers += 1
            level = getattr(item, "level", None)
            headings_by_level[f"level_{level}" if level is not None else "level_unknown"] += 1
            if page_inv:
                page_inv.headings += 1
        elif label in _LIST_LABELS:
            inv.list_items += 1
            # `ListItem.enumerated` is the structural field Docling's own Markdown
            # serializer uses to decide "1." vs "-"; it is set per-item (so mixed
            # and nested lists are handled correctly) and does not depend on
            # guessing intent from the `marker` string, which is frequently "-"
            # even for enumerated items (D-6).
            if bool(getattr(item, "enumerated", False)):
                inv.ordered_list_items += 1
            else:
                inv.unordered_list_items += 1
            if page_inv:
                page_inv.list_items += 1
        elif label == DocItemLabel.CAPTION:
            inv.captions += 1
            if page_inv:
                page_inv.captions += 1
        elif label == DocItemLabel.FORMULA:
            inv.formulas += 1
            if page_inv:
                page_inv.formulas += 1
        elif label == DocItemLabel.CODE:
            inv.code_blocks += 1
            if page_inv:
                page_inv.code_blocks += 1
        elif isinstance(item, TextItem) and label not in _FURNITURE_LABELS:
            inv.paragraphs += 1

    inv.headings_by_level = dict(sorted(headings_by_level.items()))
    inv.label_counts = dict(sorted(label_counts.items()))
    inv.pages = [pages[k] for k in sorted(pages)]
    return inv


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

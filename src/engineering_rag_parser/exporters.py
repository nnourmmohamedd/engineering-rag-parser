"""Asset extraction and deterministic Markdown export.

Docling's Markdown serializer is the source of truth for text, headings, lists
and reading order. This module adds only post-processing that is deterministic,
separately testable, and — critically — *additive*: it never drops semantic
content, and it repairs two concrete losses observed in the installed
serializer.

Observed losses this module repairs
-----------------------------------
1. **Zero-cell tables vanish entirely.** When TableFormer detects a table region
   but recovers no cells (which happens when the table body is a raster image
   with no text layer), ``export_to_markdown`` emits *nothing at all* — not even
   a placeholder. A reader sees the caption "Table 1: …" followed by silence.
   Repaired by inserting an explicit marker into a **deep copy** of the document
   at the table's exact reading-order position, using
   ``DoclingDocument.insert_text(sibling=…)``. The canonical JSON is serialised
   from the untouched original.

2. **Repeated decorative imagery floods the body.** The layout model reports a
   picture for every fragment of the page banner, so the body would carry ~99
   image references that are pure furniture. These are removed from the canonical
   body and retained in the audit inventory with the evidence that classified
   them.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docling_core.types.doc import (
    ContentLayer,
    DocItemLabel,
    DoclingDocument,
    ImageRefMode,
    PictureItem,
    TableItem,
)

from .artifacts import RunDirectory, safe_filename
from .config import ParserConfig
from .domain import PictureFinding, Severity, SourceManifest, TableFinding
from .normalization import normalize_line

__all__ = [
    "ExportResult",
    "classify_pictures",
    "export_assets",
    "export_markdown",
    "find_table_labels",
]

logger = logging.getLogger(__name__)

_IMAGE_PLACEHOLDER = "<!-- image -->"
_PAGE_BREAK = "<!--ERP:PAGEBREAK-->"
_TABLE_MARK = "<!--ERP:TABLE:{index}-->"
_TABLE_MARK_RE = re.compile(r"<!--ERP:TABLE:(\d+)-->")
#: Matches "Table 1:" / "Table 12 " style labels wherever they appear in text.
_TABLE_LABEL_RE = re.compile(r"\bTable\s+(\d+)\b", re.IGNORECASE)

#: Values PDF writers put in /Title when the author never set one. Treated as
#: absent rather than promoted into an H1 that says "(anonymous)".
_PLACEHOLDER_TITLES = frozenset({"anonymous", "untitled", "unknown", "document", "", "none"})


@dataclass
class ExportResult:
    """Everything the exporter produced, for the manifest and validators."""

    markdown_path: Path
    raw_markdown_path: Path | None
    audit_markdown_path: Path | None
    picture_findings: list[PictureFinding]
    table_findings: list[TableFinding]
    asset_paths: list[str]
    page_image_paths: dict[int, str]
    removed_furniture: list[dict[str, Any]]
    synthesized_title: str | None
    stats: dict[str, Any]


def _bbox_tuple(item: Any) -> tuple[float, float, float, float] | None:
    """First provenance bbox as ``(l, b, r, t)`` in PDF points."""
    provs = list(getattr(item, "prov", []) or [])
    if not provs:
        return None
    b = provs[0].bbox
    return (float(b.l), float(b.b), float(b.r), float(b.t))


def _page_no(item: Any) -> int | None:
    provs = list(getattr(item, "prov", []) or [])
    return int(provs[0].page_no) if provs else None


def _overlap_fraction(
    inner: tuple[float, float, float, float], outer: tuple[float, float, float, float]
) -> float:
    """Fraction of ``inner``'s area that lies inside ``outer``."""
    ix0 = max(inner[0], outer[0])
    iy0 = max(inner[1], outer[1])
    ix1 = min(inner[2], outer[2])
    iy1 = min(inner[3], outer[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    inner_area = (inner[2] - inner[0]) * (inner[3] - inner[1])
    return inter / inner_area if inner_area > 0 else 0.0


def classify_pictures(
    document: DoclingDocument, manifest: SourceManifest, config: ParserConfig
) -> list[PictureFinding]:
    """Label each Docling picture as substantive or decorative.

    Classification is driven by the **independent preflight inventory**, not by
    Docling's own output: preflight already knows the exact bounding boxes of
    every raster image and which of those signatures repeat across the document.
    A Docling picture region that sits inside a repeated banner/watermark region
    is furniture; one that sits over a non-repeated image is a real figure.

    A pure area threshold is used only as a fallback for regions that match no
    source image at all, so a genuine diagram can never be discarded merely for
    being small.
    """
    substantive_regions: dict[int, list[tuple[float, float, float, float]]] = {}
    repeated_regions: dict[int, list[tuple[float, float, float, float]]] = {}
    page_area: dict[int, float] = {}
    for page in manifest.pages:
        page_area[page.page_no] = (page.width_pt * page.height_pt) or 1.0
        for block in page.images:
            if block.bbox is None:
                continue
            target = repeated_regions if block.is_repeated else substantive_regions
            target.setdefault(page.page_no, []).append(block.bbox)

    findings: list[PictureFinding] = []
    for idx, picture in enumerate(document.pictures):
        page_no = _page_no(picture)
        bbox = _bbox_tuple(picture)
        area_fraction = 0.0
        if bbox and page_no:
            area_fraction = abs((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) / page_area.get(page_no, 1.0)

        classification = "unknown"
        notes: list[str] = []
        if bbox is None or page_no is None:
            classification = "unknown"
            notes.append("Picture has no provenance; cannot localise it on a page.")
        else:
            best_sub = max(
                (_overlap_fraction(bbox, r) for r in substantive_regions.get(page_no, [])), default=0.0
            )
            best_rep = max(
                (_overlap_fraction(bbox, r) for r in repeated_regions.get(page_no, [])), default=0.0
            )
            if best_sub >= 0.5 and best_sub >= best_rep:
                classification = "substantive"
                notes.append(f"Overlaps a non-repeated source image region ({best_sub:.0%} contained).")
            elif best_rep >= 0.5:
                classification = "decorative_repeated"
                notes.append(
                    f"Contained ({best_rep:.0%}) in a source image whose signature repeats across pages "
                    "(page banner / watermark)."
                )
            elif area_fraction >= config.thresholds.image_heavy_area_fraction:
                classification = "substantive"
                notes.append(
                    f"Matches no source raster region but covers {area_fraction:.1%} of the page; "
                    "retained as substantive rather than risk discarding a figure."
                )
            else:
                classification = "small"
                notes.append(
                    f"No overlap with a source image region and only {area_fraction:.2%} of the page."
                )

        caption = ""
        try:
            caption = (picture.caption_text(document) or "").strip()
        except Exception:  # noqa: BLE001
            caption = ""

        findings.append(
            PictureFinding(
                picture_index=idx,
                self_ref=picture.self_ref,
                page_no=page_no,
                caption=caption,
                bbox=bbox,
                area_fraction=round(area_fraction, 5),
                classification=classification,  # type: ignore[arg-type]
                severity=Severity.INFO,
                notes=notes,
            )
        )
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.classification] = counts.get(f.classification, 0) + 1
    logger.info("Picture classification: %s", counts)
    return findings


def find_table_labels(
    document: DoclingDocument, native_texts: dict[int, str] | None = None
) -> dict[int, dict[str, Any]]:
    """Locate ``Table N`` labels from document evidence, independently of ``document.tables``.

    Gate 8 requires Tables 1, 2 and 3 to be *located and individually reported*.
    On the acceptance document Docling detects only two table regions and misses
    one entirely, so relying on ``document.tables`` alone would silently
    under-report. Labels are therefore discovered from caption text — preferring
    the **native** PDF text so the finding does not depend on Docling being right
    — and Docling's recovery at each location is audited against them.

    Table numbering is not assumed to follow page order: each label carries the
    page where it was actually found.

    Returns ``{table_number: {"page_no", "title", "source"}}``.
    """
    labels: dict[int, dict[str, Any]] = {}

    def consider(text: str, page_no: int | None, source: str) -> None:
        stripped = text.strip()
        match = _TABLE_LABEL_RE.match(stripped)
        if not match:
            return
        number = int(match.group(1))
        # A caption reads "Table 1: <title>"; prose reads "Table 1 illustrates …".
        # Only the former names the table.
        rest = stripped[match.end() :].lstrip()
        if not rest.startswith(":"):
            return
        title = rest.lstrip(":").strip()
        if number not in labels:
            labels[number] = {"page_no": page_no, "title": title, "source": source}

    # Native text first: it is the independent baseline.
    for page_no, text in sorted((native_texts or {}).items()):
        for line in text.splitlines():
            consider(line, page_no, "native_pdf_text")

    for item, _lvl in document.iterate_items(
        with_groups=False,
        included_content_layers={ContentLayer.BODY, ContentLayer.FURNITURE},
    ):
        text = getattr(item, "text", "") or ""
        if text:
            consider(text, _page_no(item), "docling_text")

    return dict(sorted(labels.items()))


def export_assets(
    document: DoclingDocument,
    run: RunDirectory,
    config: ParserConfig,
    picture_findings: list[PictureFinding],
) -> tuple[list[str], dict[int, str]]:
    """Write picture and page images into the run directory.

    Only substantive pictures get an asset: writing 99 copies of a banner
    fragment would bury the 15 figures that matter. Decorative classifications
    are still recorded in the report, so the decision remains auditable.
    """
    from .artifacts import sha256_file

    asset_paths: list[str] = []
    by_index = {f.picture_index: f for f in picture_findings}

    for idx, picture in enumerate(document.pictures):
        finding = by_index.get(idx)
        if finding is None or finding.classification not in {"substantive", "unknown"}:
            continue
        try:
            image = picture.get_image(document)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not extract image for picture %d: %s", idx, exc)
            finding.notes.append(f"Image extraction failed: {exc}")
            finding.severity = Severity.WARNING
            continue
        if image is None:
            finding.notes.append("Docling holds no raster for this picture region.")
            finding.severity = Severity.WARNING
            continue
        name = f"page{finding.page_no or 0:03d}-picture{idx:03d}.png"
        rel = f"{config.export.image_subdir}/{safe_filename(name)}"
        path = run.path_for(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, format="PNG", optimize=True)
        finding.asset_path = rel
        finding.asset_sha256 = sha256_file(path)
        asset_paths.append(rel)

    page_images: dict[int, str] = {}
    if config.export.save_page_images:
        for page_no, page in document.pages.items():
            if page.image is None:
                continue
            try:
                image = page.image.pil_image
            except Exception as exc:  # noqa: BLE001
                logger.debug("No PIL image for page %s: %s", page_no, exc)
                continue
            if image is None:
                continue
            rel = f"{config.export.page_image_subdir}/page{int(page_no):03d}.png"
            path = run.path_for(rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            image.save(path, format="PNG", optimize=True)
            page_images[int(page_no)] = rel

    logger.info("Assets: %d picture(s), %d page image(s)", len(asset_paths), len(page_images))
    return asset_paths, page_images


def _table_asset(
    document: DoclingDocument, table: TableItem, index: int, run: RunDirectory, config: ParserConfig
) -> tuple[str | None, str | None]:
    """Save the raster crop of a table region so an unrecovered table is never lost."""
    from .artifacts import sha256_file

    try:
        image = table.get_image(document)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not crop table %d: %s", index, exc)
        return None, None
    if image is None:
        return None, None
    rel = f"{config.export.image_subdir}/page{_page_no(table) or 0:03d}-table{index:03d}.png"
    path = run.path_for(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)
    return rel, sha256_file(path)


def _audit_tables(
    document: DoclingDocument,
    run: RunDirectory,
    config: ParserConfig,
    table_labels: dict[int, dict[str, Any]],
) -> tuple[list[TableFinding], dict[int, str]]:
    """Audit every Docling table and decide how it will be serialised.

    Returns the findings plus ``{table_index: markdown_block}`` for tables that
    the Docling serializer would otherwise drop.
    """
    findings: list[TableFinding] = []
    replacements: dict[int, str] = {}

    # Map "which Table N caption sits on this page" so an unlabelled region can
    # still be tied to the document's own numbering.
    page_to_label = {
        info["page_no"]: (num, info) for num, info in table_labels.items() if info.get("page_no")
    }

    for index, table in enumerate(document.tables):
        data = table.data
        num_rows = int(getattr(data, "num_rows", 0) or 0)
        num_cols = int(getattr(data, "num_cols", 0) or 0)
        cells = list(getattr(data, "table_cells", []) or [])
        page_no = _page_no(table)
        try:
            caption = (table.caption_text(document) or "").strip()
        except Exception:  # noqa: BLE001
            caption = ""

        detected_label: str | None = None
        if caption:
            m = _TABLE_LABEL_RE.match(caption.strip())
            if m:
                detected_label = f"Table {int(m.group(1))}"
        if detected_label is None and page_no in page_to_label:
            detected_label = f"Table {page_to_label[page_no][0]}"

        empty_cells = sum(1 for c in cells if not (getattr(c, "text", "") or "").strip())
        empty_ratio = (empty_cells / len(cells)) if cells else 1.0
        has_merged = any(
            int(getattr(c, "row_span", 1) or 1) > 1 or int(getattr(c, "col_span", 1) or 1) > 1 for c in cells
        )
        is_rect = bool(cells) and len(cells) == num_rows * num_cols

        finding = TableFinding(
            table_index=index,
            self_ref=table.self_ref,
            page_no=page_no,
            caption=caption,
            detected_label=detected_label,
            num_rows=num_rows,
            num_cols=num_cols,
            num_cells=len(cells),
            empty_cell_ratio=round(empty_ratio, 4),
            is_rectangular=is_rect,
            has_merged_cells=has_merged,
        )

        if not cells:
            # No cells recovered. The region is real (the layout model found it)
            # but its content is not text. Preserve the crop and say so loudly;
            # never emit an empty Markdown table that implies the table was read.
            rel, sha = _table_asset(document, table, index, run, config)
            finding.serialization = "asset_only"
            finding.severity = Severity.CRITICAL
            finding.notes.append(
                "TableFormer detected the region but recovered 0 cells: the table body carries no "
                "extractable text layer (it is a raster image). Content NOT machine-readable."
            )
            label = detected_label or f"table region {index}"
            block_lines = [
                f"> **⚠ Unrecovered table — {label}** (page {page_no}). "
                "Docling located this table region but recovered no cells, because the table body is a "
                "raster image with no text layer. The region is preserved below as an image asset. "
                "**Its contents are not machine-readable and require human review or a targeted OCR pass.**",
            ]
            if rel:
                finding.notes.append(f"Region preserved as asset: {rel}")
                block_lines.append("")
                block_lines.append(f"![{label} (unrecovered table region)]({rel})")
                replacements[index] = "\n".join(block_lines)
            else:
                finding.notes.append("Region crop could not be produced; only this warning marks the loss.")
                replacements[index] = "\n".join(block_lines)
        elif has_merged or not is_rect:
            finding.serialization = "html" if config.export.complex_table_as_html else "markdown"
            finding.severity = Severity.WARNING
            finding.notes.append(
                "Table has merged or ragged cells; Markdown pipe tables cannot express that, "
                "so an HTML table is used to avoid a lossy flattening."
            )
            try:
                replacements[index] = table.export_to_html(document, add_caption=True)
            except Exception as exc:  # noqa: BLE001
                finding.notes.append(f"HTML serialisation failed ({exc}); left as Markdown.")
                finding.serialization = "markdown"
        else:
            finding.serialization = "markdown"
            if empty_ratio > config.thresholds.max_empty_table_cell_ratio:
                finding.severity = Severity.WARNING
                finding.notes.append(
                    f"{empty_ratio:.0%} of recovered cells are empty, above the "
                    f"{config.thresholds.max_empty_table_cell_ratio:.0%} threshold."
                )
        findings.append(finding)

    return findings, replacements


def _strip_repeated_furniture_lines(
    markdown: str, manifest: SourceManifest, config: ParserConfig
) -> tuple[str, list[dict[str, Any]]]:
    """Drop body lines proven to be repeated header/footer furniture.

    Removal requires *positional* evidence from preflight (the line recurred in a
    header/footer band on at least ``furniture_min_page_fraction`` of pages), not
    merely that a line looks repetitive. Every removal is recorded so the report
    can show exactly what was taken out.
    """
    if not config.export.remove_repeated_furniture_text:
        return markdown, []

    furniture_keys = {
        c.normalized
        for c in manifest.furniture_candidates
        if c.band in {"header", "footer"} and not c.normalized.startswith("image:")
    }
    if not furniture_keys:
        return markdown, []

    removed: dict[str, int] = {}
    kept: list[str] = []
    for line in markdown.split("\n"):
        stripped = line.strip()
        if stripped and normalize_line(stripped) in furniture_keys:
            removed[stripped] = removed.get(stripped, 0) + 1
            continue
        kept.append(line)

    evidence = [{"text": text, "occurrences": n, "reason": "repeated header/footer furniture"}
                for text, n in sorted(removed.items(), key=lambda kv: -kv[1])]
    return "\n".join(kept), evidence


_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _normalize_whitespace(text: str) -> str:
    """Collapse layout artifacts without touching content.

    The source is justified text, so Docling faithfully reproduces runs of two
    and three spaces *between words* ("These  deliverables  define  the"). Those
    runs are a typesetting artifact, not information, and they add noise to every
    downstream embedding. They are collapsed here, while:

    * leading indentation is preserved (it carries list nesting);
    * fenced code blocks and pipe-table rows are left byte-for-byte alone;
    * the untouched serializer output remains at ``markdown/document.raw.md``.
    """
    out: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        stripped = line.lstrip()
        if in_fence or stripped.startswith("|") or stripped.startswith("<"):
            out.append(line.rstrip())
            continue
        indent = line[: len(line) - len(stripped)]
        out.append((indent + re.sub(r"[ \t]{2,}", " ", stripped)).rstrip())
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def export_markdown(
    document: DoclingDocument,
    run: RunDirectory,
    config: ParserConfig,
    manifest: SourceManifest,
    picture_findings: list[PictureFinding],
    page_images: dict[int, str],
    table_labels: dict[int, dict[str, Any]],
) -> ExportResult:
    """Produce the canonical ``markdown/document.md`` plus audit copies.

    Raises:
        RuntimeError: if the number of image placeholders emitted by the
            serializer does not match the number of body-layer pictures. That
            would mean the positional mapping is unsafe, and a wrong mapping
            (a diagram replaced by the wrong asset) is worse than failing.
    """
    table_findings, table_replacements = _audit_tables(document, run, config, table_labels)

    # --- Render from a deep copy so markers never contaminate the canonical JSON.
    md_doc = document.model_copy(deep=True)
    for index, table in enumerate(md_doc.tables):
        if index in table_replacements:
            md_doc.insert_text(
                sibling=table,
                label=DocItemLabel.TEXT,
                text=_TABLE_MARK.format(index=index),
                prov=table.prov[0] if table.prov else None,
                after=True,
            )

    layers = {ContentLayer.BODY} if config.export.strip_furniture else {
        ContentLayer.BODY, ContentLayer.FURNITURE
    }
    raw_markdown = md_doc.export_to_markdown(
        image_mode=ImageRefMode.PLACEHOLDER,
        image_placeholder=_IMAGE_PLACEHOLDER,
        # Engineering acronyms must survive: the serializer default escapes
        # "C&I" to "C&amp;I" and "FT_101" to "FT\_101", corrupting the tokens
        # that downstream retrieval depends on.
        escape_html=False,
        escape_underscores=config.export.escape_underscores,
        included_content_layers=layers,
        page_break_placeholder=_PAGE_BREAK,
    )

    raw_path: Path | None = None
    if config.export.keep_raw_serializer_output:
        raw_path = run.write_text("markdown/document.raw.md", raw_markdown)

    audit_markdown = document.export_to_markdown(
        image_mode=ImageRefMode.PLACEHOLDER,
        escape_html=False,
        escape_underscores=config.export.escape_underscores,
        included_content_layers={ContentLayer.BODY, ContentLayer.FURNITURE, ContentLayer.BACKGROUND},
        page_break_placeholder=_PAGE_BREAK,
    )
    audit_path = run.write_text("markdown/document.with-furniture.md", audit_markdown)

    # --- Substitute table markers (exact reading-order positions).
    def sub_table(match: re.Match[str]) -> str:
        return table_replacements.get(int(match.group(1)), "")

    body = _TABLE_MARK_RE.sub(sub_table, raw_markdown)

    # --- Substitute image placeholders positionally.
    body_pictures = [
        item
        for item, _lvl in md_doc.iterate_items(with_groups=False, included_content_layers=layers)
        if isinstance(item, PictureItem)
    ]
    placeholder_count = body.count(_IMAGE_PLACEHOLDER)
    if placeholder_count != len(body_pictures):
        raise RuntimeError(
            f"Image placeholder mismatch: serializer emitted {placeholder_count} placeholders but the "
            f"body layer holds {len(body_pictures)} pictures. Refusing to map assets positionally, "
            "because a wrong mapping would attach the wrong figure to a diagram."
        )

    findings_by_ref = {f.self_ref: f for f in picture_findings}
    replacements: list[str] = []
    dropped_decorative = 0
    for picture in body_pictures:
        finding = findings_by_ref.get(picture.self_ref)
        if finding is None or finding.classification in {"decorative_repeated", "small"}:
            dropped_decorative += 1
            replacements.append("")
            continue
        caption = finding.caption or f"Figure on page {finding.page_no}"
        if finding.asset_path:
            replacements.append(f"![{caption}]({finding.asset_path})")
        else:
            replacements.append(
                f"> **⚠ Unextracted figure** on page {finding.page_no}: Docling reported a picture "
                "region but no raster could be written. Flagged for human review."
            )

    iterator = iter(replacements)
    body = re.sub(re.escape(_IMAGE_PLACEHOLDER), lambda _m: next(iterator), body)

    # --- Page anchors from the serializer's own page breaks.
    segments = body.split(_PAGE_BREAK)
    page_numbers = sorted(int(p) for p in document.pages)
    if config.export.emit_page_anchors and len(segments) == len(page_numbers):
        rebuilt: list[str] = []
        for page_no, segment in zip(page_numbers, segments, strict=True):
            anchor = config.export.page_anchor_template.format(page_no=page_no)
            rebuilt.append(f"{anchor}\n{segment.strip()}")
        body = "\n\n".join(rebuilt)
    else:
        if config.export.emit_page_anchors:
            logger.warning(
                "Page-break count (%d) does not match page count (%d); emitting Markdown without "
                "page anchors rather than mislabelling provenance.",
                len(segments), len(page_numbers),
            )
        body = body.replace(_PAGE_BREAK, "\n\n")

    body, removed_furniture = _strip_repeated_furniture_lines(body, manifest, config)

    # --- Document title.
    synthesized_title: str | None = None
    has_title = any(
        getattr(i, "label", None) == DocItemLabel.TITLE
        for i, _l in document.iterate_items(with_groups=False)
    )
    if not has_title:
        # The visible title may live inside a banner image, so no text item carries
        # it. Fall back to the PDF's own /Title metadata — a sourced value, not an
        # invention — and record that it was synthesized. Writers commonly emit a
        # placeholder there ("(anonymous)", "untitled"), which is not a title.
        meta_title = (manifest.metadata.get("Title") or "").strip()
        if meta_title.strip("()").casefold() in _PLACEHOLDER_TITLES:
            meta_title = ""
        synthesized_title = meta_title or Path(manifest.filename).stem.replace("-", " ")
        body = f"# {synthesized_title}\n\n{body}"

    body = _normalize_whitespace(body)
    markdown_path = run.write_text("markdown/document.md", body)

    stats = {
        "characters": len(body),
        "lines": body.count("\n") + 1,
        "image_links": body.count("!["),
        "decorative_pictures_dropped": dropped_decorative,
        "tables_asset_only": sum(1 for t in table_findings if t.serialization == "asset_only"),
        "tables_html": sum(1 for t in table_findings if t.serialization == "html"),
        "furniture_lines_removed": sum(int(e["occurrences"]) for e in removed_furniture),
        "title_synthesized": synthesized_title is not None,
    }
    logger.info("Markdown export: %s", stats)

    return ExportResult(
        markdown_path=markdown_path,
        raw_markdown_path=raw_path,
        audit_markdown_path=audit_path,
        picture_findings=picture_findings,
        table_findings=table_findings,
        asset_paths=[f.asset_path for f in picture_findings if f.asset_path],
        page_image_paths=page_images,
        removed_furniture=removed_furniture,
        synthesized_title=synthesized_title,
        stats=stats,
    )

"""Structural validation: headings, lists, TOC, tables and pictures.

Checks here answer "did the document keep its shape", which text coverage
cannot see. A page can retain every character while losing the heading that
tells a retriever what the section is about.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from docling_core.types.doc import ContentLayer, DocItemLabel, DoclingDocument

from engineering_rag_parser.config import ParserConfig
from engineering_rag_parser.domain import (
    CheckResult,
    DocumentInventory,
    PictureFinding,
    Severity,
    SourceManifest,
    TableFinding,
)

__all__ = ["structure_checks", "table_checks"]

logger = logging.getLogger(__name__)

#: "Section 3", "2.5", "6.4" — numbering schemes present in this document class.
_SECTION_NUM_RE = re.compile(r"^\s*(?:Section\s+)?(\d+(?:\.\d+)*)\b", re.IGNORECASE)


def _headings(document: DoclingDocument) -> list[tuple[int, str]]:
    """Ordered ``(level, text)`` for every heading in the body layer."""
    out: list[tuple[int, str]] = []
    for item, _lvl in document.iterate_items(with_groups=False, included_content_layers={ContentLayer.BODY}):
        label = getattr(item, "label", None)
        if label == DocItemLabel.TITLE:
            out.append((1, (getattr(item, "text", "") or "").strip()))
        elif label == DocItemLabel.SECTION_HEADER:
            level = int(getattr(item, "level", 1) or 1)
            out.append((level + 1, (getattr(item, "text", "") or "").strip()))
    return out


def structure_checks(
    document: DoclingDocument,
    inventory: DocumentInventory,
    manifest: SourceManifest,
    pictures: list[PictureFinding],
) -> list[CheckResult]:
    """Run the structural inventory checks."""
    checks: list[CheckResult] = []
    headings = _headings(document)

    # --- Headings exist at all ------------------------------------------------
    checks.append(
        CheckResult(
            check_id="headings_present",
            title="Document has a heading structure",
            passed=bool(headings),
            severity=Severity.CRITICAL,
            gate=True,
            summary=f"{len(headings)} heading(s) recovered across {inventory.page_count} pages.",
            evidence={
                "headings_by_level": inventory.headings_by_level,
                "sample": [h[1][:70] for h in headings[:8]],
            },
            threshold={"required": ">= 1 heading"},
            remediation="A document with no headings cannot be chunked section-wise downstream.",
        )
    )

    # --- Heading level jumps --------------------------------------------------
    jumps: list[dict[str, Any]] = []
    previous = None
    for level, text in headings:
        if previous is not None and level > previous + 1:
            jumps.append({"from_level": previous, "to_level": level, "heading": text[:80]})
        previous = level
    checks.append(
        CheckResult(
            check_id="heading_hierarchy_consistent",
            title="Heading levels do not skip",
            passed=not jumps,
            severity=Severity.WARNING,
            gate=False,
            summary="Heading levels increase by at most one step."
            if not jumps
            else f"{len(jumps)} heading-level jump(s) detected.",
            evidence={"jumps": jumps[:10]},
            threshold={"rule": "level(n) <= level(n-1) + 1"},
            remediation="A skipped level usually means an intermediate heading was classified as body text.",
        )
    )

    # --- Numbered sections vs bookmarks ---------------------------------------
    # The TOC/outline is independent evidence of what sections should exist. The
    # check compares *numbering*, never the exact extracted wording, so a
    # harmless whitespace or dash difference cannot fail it.
    outline_numbers = set()
    for entry in manifest.outline_entries:
        m = _SECTION_NUM_RE.match(str(entry.get("title", "")))
        if m:
            outline_numbers.add(m.group(1))
    heading_numbers = set()
    for _lvl, text in headings:
        m = _SECTION_NUM_RE.match(text)
        if m:
            heading_numbers.add(m.group(1))
    missing_sections = sorted(outline_numbers - heading_numbers, key=_numeric_key)
    coverage = len(outline_numbers & heading_numbers) / len(outline_numbers) if outline_numbers else 1.0
    checks.append(
        CheckResult(
            check_id="toc_sections_recovered",
            title="Numbered sections from the document outline appear as headings",
            passed=coverage >= 0.8,
            severity=Severity.WARNING,
            gate=False,
            summary=(
                f"{len(outline_numbers & heading_numbers)}/{len(outline_numbers)} outline section numbers "
                f"({coverage:.0%}) were recovered as headings."
                if outline_numbers
                else "Document exposes no numbered outline entries; check skipped by absence of evidence."
            ),
            evidence={
                "outline_numbers": sorted(outline_numbers, key=_numeric_key)[:40],
                "missing_from_headings": missing_sections[:40],
                "outline_entry_count": len(manifest.outline_entries),
            },
            threshold={"min_coverage": 0.8},
            remediation="Sections present in the outline but absent from headings were likely "
            "classified as body text; inspect those pages.",
        )
    )

    # --- Orphan captions ------------------------------------------------------
    orphan_captions = _orphan_captions(document)
    checks.append(
        CheckResult(
            check_id="captions_attached",
            title="Captions are attached to a figure or table",
            passed=not orphan_captions,
            severity=Severity.WARNING,
            gate=False,
            summary="All captions are attached to an object."
            if not orphan_captions
            else f"{len(orphan_captions)} caption(s) have no parent figure/table.",
            evidence={"orphans": orphan_captions[:10]},
            threshold={"rule": "every caption item must be referenced by a picture or table"},
            remediation="An orphan caption means the object it describes was not detected.",
        )
    )

    # --- Substantive figures represented --------------------------------------
    # Cross-check the independent preflight figure inventory against what Docling
    # produced. A source figure with no corresponding Docling region is a real
    # loss, regardless of how good the text metrics look.
    represented_pages = {f.page_no for f in pictures if f.classification == "substantive" and f.page_no}
    table_pages = {int(t.prov[0].page_no) for t in document.tables if t.prov}
    covered_pages = represented_pages | table_pages
    expected_pages = set(manifest.pages_with_substantive_images)
    unrepresented = sorted(expected_pages - covered_pages)
    checks.append(
        CheckResult(
            check_id="substantive_figures_represented",
            title="Every non-repeated source figure is represented in the parse",
            passed=not unrepresented,
            severity=Severity.CRITICAL,
            gate=True,
            summary=(
                f"All {len(expected_pages)} page(s) carrying a substantive figure are represented "
                "by a Docling picture or table region."
                if not unrepresented
                else f"Pages whose figure has no Docling region: {unrepresented}"
            ),
            evidence={
                "source_figure_pages": sorted(expected_pages),
                "docling_picture_pages": sorted(represented_pages),
                "docling_table_pages": sorted(table_pages),
                "unrepresented_pages": unrepresented,
            },
            threshold={"required": "every page with a non-repeated source image has a Docling region"},
            remediation="Preserve the page render for the affected page and flag it for human review.",
        )
    )

    # --- Decorative separation ------------------------------------------------
    decorative = [p for p in pictures if p.classification == "decorative_repeated"]
    substantive = [p for p in pictures if p.classification == "substantive"]
    checks.append(
        CheckResult(
            check_id="decorative_assets_separated",
            title="Repeated decorative imagery is distinguished from substantive diagrams",
            passed=bool(substantive) or not pictures,
            severity=Severity.INFO,
            gate=False,
            summary=(
                f"{len(substantive)} substantive figure(s), {len(decorative)} decorative repeats, "
                f"{len(pictures) - len(substantive) - len(decorative)} other."
            ),
            evidence={
                "substantive_pages": sorted({p.page_no for p in substantive if p.page_no}),
                "decorative_count": len(decorative),
                "classification_basis": "overlap with preflight raster regions whose (bbox, px-size) "
                "signature repeats across pages",
            },
            threshold={"rule": "classification is evidence-based, not size-based"},
            remediation="",
        )
    )

    return checks


def _numeric_key(value: str) -> tuple[int, ...]:
    """Sort '2.10' after '2.9' by comparing numeric components."""
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return (9999,)


def _orphan_captions(document: DoclingDocument) -> list[str]:
    """Caption items not referenced by any picture or table."""
    referenced: set[str] = set()
    for holder in list(document.pictures) + list(document.tables):
        for ref in getattr(holder, "captions", []) or []:
            cref = getattr(ref, "cref", None) or getattr(ref, "$ref", None)
            if cref:
                referenced.add(str(cref))
    orphans: list[str] = []
    for item, _lvl in document.iterate_items(with_groups=False, included_content_layers={ContentLayer.BODY}):
        if getattr(item, "label", None) == DocItemLabel.CAPTION and item.self_ref not in referenced:
            orphans.append((getattr(item, "text", "") or "")[:100])
    return orphans


def table_checks(
    tables: list[TableFinding],
    table_labels: dict[int, dict[str, Any]],
    config: ParserConfig,
    markdown_text: str = "",
    run_root: Path | None = None,
    pictures: list[PictureFinding] | None = None,
) -> list[CheckResult]:
    """Audit the labelled tables (Table 1, Table 2, Table 3 …) individually."""
    checks: list[CheckResult] = []
    pictures = pictures or []

    # --- Every labelled table is located --------------------------------------
    located = {}
    for number, info in table_labels.items():
        matching = [t for t in tables if t.detected_label == f"Table {number}"]
        caption_page = info.get("page_no")
        entry: dict[str, Any] = {
            "page_no": caption_page,
            "title": info.get("title"),
            "evidence_source": info.get("source"),
            "docling_regions": len(matching),
            "region_pages": [t.page_no for t in matching],
            "serialization": [t.serialization for t in matching],
            "cells_recovered": sum(t.num_cells for t in matching),
            "assets": [
                n.split(": ", 1)[1]
                for t in matching
                for n in t.notes
                if n.startswith("Region preserved as asset: ")
            ],
        }
        if not matching:
            # Docling may classify a raster table as a *picture* rather than a
            # table. The content is then still preserved, just under a different
            # label — record that instead of leaving the table unaccounted for.
            covering = [
                p
                for p in pictures
                if p.classification == "substantive"
                and p.asset_path
                and p.page_no in {caption_page, (caption_page or 0) + 1}
            ]
            entry["covered_by_picture_regions"] = [
                {"page_no": p.page_no, "asset_path": p.asset_path, "area_fraction": p.area_fraction}
                for p in covering
            ]
            entry["outcome"] = (
                "No Docling TABLE region. The body is preserved as a figure asset on page "
                f"{covering[0].page_no}; its cells are not machine-readable."
                if covering
                else "No Docling table or picture region found for this label — requires manual review."
            )
        else:
            entry["outcome"] = (
                f"Docling table region on page {matching[0].page_no}, serialized as "
                f"'{matching[0].serialization}' with {entry['cells_recovered']} cell(s)."
            )
        located[number] = entry

    unlocated = [n for n, v in located.items() if v["docling_regions"] == 0]
    # A label is only truly unaccounted for when nothing at all covers it.
    unaccounted = [n for n in unlocated if not located[n].get("covered_by_picture_regions")]
    checks.append(
        CheckResult(
            check_id="labelled_tables_located",
            title="Every labelled table is located and individually reported",
            passed=bool(located) and not unaccounted,
            severity=Severity.CRITICAL,
            gate=True,
            summary=(
                f"Located {len(located)} labelled table(s) from native PDF text: "
                + ", ".join(f"Table {n} (caption p{v['page_no']})" for n, v in sorted(located.items()))
                + (
                    f". Detected as a picture region rather than a table: "
                    f"{[f'Table {n}' for n in unlocated if n not in unaccounted]}"
                    if [n for n in unlocated if n not in unaccounted]
                    else ""
                )
                + (f". UNACCOUNTED: {[f'Table {n}' for n in unaccounted]}" if unaccounted else "")
            ),
            evidence={"tables": located},
            threshold={
                "rule": "each 'Table N:' caption found in the source is reported with page, title and "
                "the outcome of its region — whether Docling classified it as a table or a picture"
            },
            remediation="A labelled table with no Docling table region has its body preserved as a "
            "figure asset; its cells are not machine-readable and need transcription.",
        )
    )

    # --- Cell recovery --------------------------------------------------------
    # This is a WARNING, not a gate. Zero cell recovery here is a property of the
    # *source* (a table drawn as a raster image has no text to recover), not a
    # parser defect. What must never happen is that such a table disappears
    # quietly — that is gated separately by `unrecovered_content_preserved`.
    unrecovered = [t for t in tables if t.serialization == "asset_only"]
    checks.append(
        CheckResult(
            check_id="table_cells_recovered",
            title="Detected tables yield machine-readable cells",
            passed=not unrecovered,
            severity=Severity.WARNING,
            gate=False,
            summary=(
                f"All {len(tables)} detected table(s) produced cells."
                if not unrecovered
                else f"{len(unrecovered)} of {len(tables)} detected table region(s) recovered ZERO cells "
                f"(pages {[t.page_no for t in unrecovered]}); their bodies are raster images with no "
                "text layer. Preserved as image assets and flagged for human transcription."
            ),
            evidence={
                "unrecovered": [
                    {
                        "table_index": t.table_index,
                        "page_no": t.page_no,
                        "label": t.detected_label,
                        "caption": t.caption[:120],
                        "notes": t.notes,
                    }
                    for t in unrecovered
                ]
            },
            threshold={"rule": "a detected table region should yield >= 1 cell"},
            remediation="Run the OCR-enabled profile against those pages, or transcribe them manually. "
            "Do not treat the Markdown as containing their content.",
        )
    )

    # --- No silent loss -------------------------------------------------------
    # THE gate that matters for unrecovered content: a table whose cells could not
    # be read is acceptable; a table that vanishes without an asset and a visible
    # warning is not. This proves, on the artifacts themselves, that every such
    # region left both a preserved image and an explicit marker in the Markdown.
    preservation: list[dict[str, Any]] = []
    for table in unrecovered:
        asset_note = next((n for n in table.notes if n.startswith("Region preserved as asset: ")), None)
        asset_rel = asset_note.split(": ", 1)[1] if asset_note else None
        # `is not None` (rather than a truthiness test) so the optional path is
        # narrowed to `str` for the join and the substring search below.
        asset_exists = asset_rel is not None and run_root is not None and (run_root / asset_rel).is_file()
        label = table.detected_label or f"table region {table.table_index}"
        flagged = ("Unrecovered table" in markdown_text) and (
            label in markdown_text or f"page {table.page_no}" in markdown_text
        )
        linked = asset_rel is not None and asset_rel in markdown_text
        preservation.append(
            {
                "table_index": table.table_index,
                "page_no": table.page_no,
                "label": label,
                "asset_path": asset_rel,
                "asset_exists": asset_exists,
                "warning_in_markdown": flagged,
                "asset_linked_in_markdown": linked,
            }
        )
    unpreserved = [p for p in preservation if not (p["asset_exists"] and p["warning_in_markdown"])]
    checks.append(
        CheckResult(
            check_id="unrecovered_content_preserved",
            title="Content that could not be machine-read is preserved as an asset and flagged",
            passed=not unpreserved,
            severity=Severity.CRITICAL,
            gate=True,
            summary=(
                "No unrecovered table regions."
                if not preservation
                else f"All {len(preservation)} unrecovered table region(s) are preserved as image assets "
                "and carry an explicit warning in the Markdown."
                if not unpreserved
                else f"{len(unpreserved)} unrecovered region(s) are NOT properly preserved/flagged — "
                "this is silent loss."
            ),
            evidence={"regions": preservation},
            threshold={
                "rule": "every zero-cell table region must have a written image asset AND a "
                "visible warning in the canonical Markdown"
            },
            remediation="Silent loss is the one unacceptable outcome; re-run the export so the region "
            "is written and marked.",
        )
    )

    # --- Empty cell ratio -----------------------------------------------------
    sparse = [
        t for t in tables if t.num_cells and t.empty_cell_ratio > config.thresholds.max_empty_table_cell_ratio
    ]
    checks.append(
        CheckResult(
            check_id="table_cell_density",
            title="Recovered tables are not mostly empty",
            passed=not sparse,
            severity=Severity.WARNING,
            gate=False,
            summary="All recovered tables have acceptable cell density."
            if not sparse
            else f"{len(sparse)} table(s) exceed the empty-cell ratio threshold.",
            evidence={
                "tables": [
                    {
                        "table_index": t.table_index,
                        "page_no": t.page_no,
                        "empty_cell_ratio": t.empty_cell_ratio,
                    }
                    for t in sparse
                ]
            },
            threshold={"max_empty_table_cell_ratio": config.thresholds.max_empty_table_cell_ratio},
            remediation="A mostly-empty table usually means cell matching failed; try table_mode=accurate.",
        )
    )

    # --- Suspicious 1x1 tables ------------------------------------------------
    tiny = [t for t in tables if t.num_cells == 1]
    checks.append(
        CheckResult(
            check_id="no_single_cell_tables",
            title="No single-cell tables (usually a misdetected text block)",
            passed=not tiny,
            severity=Severity.WARNING,
            gate=False,
            summary="No single-cell tables." if not tiny else f"{len(tiny)} single-cell table(s) detected.",
            evidence={"tables": [{"table_index": t.table_index, "page_no": t.page_no} for t in tiny]},
            threshold={"rule": "a table should have more than one cell"},
            remediation="Single-cell tables are usually a callout box misclassified as a table.",
        )
    )

    return checks

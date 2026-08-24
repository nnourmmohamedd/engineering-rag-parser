"""Aggregate all checks into a report, a CSV and a human-readable summary.

The report deliberately refuses to reduce to a single percentage. A run is
described by its failed gates, its warnings, and an explicit list of items a
human must look at — because "97% coverage" tells a reviewing engineer nothing
about whether the P&ID on page 11 survived.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any

from engineering_rag.services.parser.artifacts import RunDirectory
from engineering_rag.services.parser.config import ParserConfig
from engineering_rag.services.parser.models import (
    CheckResult,
    DocumentInventory,
    PageCoverage,
    PictureFinding,
    RunStatus,
    Severity,
    SourceManifest,
    TableFinding,
    ValidationReport,
)

__all__ = ["build_report", "render_markdown_report", "write_pages_csv"]

logger = logging.getLogger(__name__)

_STATUS_ICON = {
    RunStatus.PASS: "PASS",
    RunStatus.PASS_WITH_WARNINGS: "PASS_WITH_WARNINGS",
    RunStatus.FAIL: "FAIL",
}


def build_report(
    checks: list[CheckResult],
    coverage_rows: list[PageCoverage],
    tables: list[TableFinding],
    pictures: list[PictureFinding],
    manifest: SourceManifest,
    inventory: DocumentInventory,
    furniture_removed: list[dict[str, Any]],
    config: ParserConfig,
) -> ValidationReport:
    """Assemble the validation report and derive its status."""
    report = ValidationReport(
        status=RunStatus.FAIL,  # replaced below; never default to success
        strict=config.strict,
        generated_at_utc=datetime.now(timezone.utc),
        checks=checks,
        page_coverage=coverage_rows,
        tables=tables,
        pictures=[p for p in pictures if p.classification != "decorative_repeated"],
        source_inventory={
            "filename": manifest.filename,
            "sha256": manifest.sha256,
            "byte_size": manifest.byte_size,
            "page_count": manifest.page_count,
            "total_char_count": manifest.total_char_count,
            "total_word_count": manifest.total_word_count,
            "total_image_count": manifest.total_image_count,
            "substantive_image_count": manifest.substantive_image_count,
            "decorative_image_count": manifest.decorative_image_count,
            "sparse_pages": manifest.sparse_pages,
            "image_heavy_pages": manifest.image_heavy_pages,
            "visual_review_pages": manifest.visual_review_pages,
            "outline_entries": len(manifest.outline_entries),
            "fonts": manifest.fonts,
            "source_anomalies": manifest.source_anomalies,
            "tools": manifest.tools,
        },
        parsed_inventory=inventory.model_dump(mode="json", exclude={"pages"}),
        furniture_removed=furniture_removed,
        human_review_items=_human_review_items(coverage_rows, tables, pictures, manifest),
    )
    report.status = report.compute_status(config.strict)
    return report


def _human_review_items(
    coverage_rows: list[PageCoverage],
    tables: list[TableFinding],
    pictures: list[PictureFinding],
    manifest: SourceManifest,
) -> list[str]:
    """The concrete, specific list of things a person must check."""
    items: list[str] = []

    for table in tables:
        if table.serialization == "asset_only":
            label = table.detected_label or f"table region {table.table_index}"
            items.append(
                f"{label} (page {table.page_no}): body is a raster image; Docling recovered 0 cells. "
                "Transcribe manually or run the OCR profile before relying on its content."
            )

    figure_pages = manifest.pages_with_substantive_images
    if figure_pages:
        items.append(
            f"Confirm figure content on page(s) {figure_pages}: {manifest.substantive_image_count} "
            "engineering diagram(s) are preserved as image assets, but no automated check verifies that "
            "their labels, symbols or connections were recovered."
        )

    for row in coverage_rows:
        if row.severity is Severity.CRITICAL:
            items.append(f"Page {row.page_no}: {'; '.join(row.notes[:2])}")
        elif row.is_sparse_text:
            items.append(
                f"Page {row.page_no}: only {row.source_chars} native characters — completeness cannot be "
                "judged from text; review the page rendering."
            )

    unextracted = [p for p in pictures if p.classification == "substantive" and not p.asset_path]
    if unextracted:
        items.append(
            f"{len(unextracted)} substantive picture region(s) produced no image asset "
            f"(pages {sorted({p.page_no for p in unextracted if p.page_no})}); review manually."
        )

    return items


def write_pages_csv(run: RunDirectory, coverage_rows: list[PageCoverage], manifest: SourceManifest) -> str:
    """Write the per-page metrics table as CSV for spreadsheet review."""
    source_by_page = {p.page_no: p for p in manifest.pages}
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "page_no",
            "source_chars",
            "parsed_chars",
            "char_coverage",
            "furniture_chars_excluded",
            "source_chars_with_furniture",
            "source_words",
            "parsed_words",
            "token_jaccard",
            "token_recall",
            "critical_token_recall",
            "missing_critical_tokens",
            "source_images",
            "substantive_images",
            "substantive_image_area_fraction",
            "is_sparse_text",
            "is_image_heavy",
            "has_provenance",
            "needs_visual_review",
            "review_artifact",
            "severity",
            "notes",
        ]
    )
    for row in coverage_rows:
        src = source_by_page.get(row.page_no)
        writer.writerow(
            [
                row.page_no,
                row.source_chars,
                row.parsed_chars,
                f"{row.char_coverage:.4f}",
                row.furniture_chars_excluded,
                row.source_chars_with_furniture,
                row.source_words,
                row.parsed_words,
                f"{row.token_jaccard:.4f}",
                f"{row.token_recall:.4f}",
                f"{row.critical_token_recall:.4f}",
                "|".join(row.missing_critical_tokens[:10]),
                src.image_count if src else "",
                src.substantive_image_count if src else "",
                f"{src.substantive_image_area_fraction:.4f}" if src else "",
                row.is_sparse_text,
                row.is_image_heavy,
                row.has_provenance,
                row.needs_visual_review,
                row.review_artifact or "",
                row.severity.value,
                " | ".join(row.notes),
            ]
        )
    run.write_text("validation/pages.csv", buffer.getvalue())
    return "validation/pages.csv"


def render_markdown_report(report: ValidationReport, manifest: SourceManifest) -> str:
    """Render the human-readable validation report."""
    lines: list[str] = []
    add = lines.append

    add("# Validation report")
    add("")
    add(
        f"**Status: `{_STATUS_ICON[report.status]}`**"
        + (" (strict mode: warnings fail)" if report.strict else "")
    )
    add("")
    add(f"- Source: `{manifest.filename}` — {manifest.page_count} pages, {manifest.byte_size:,} bytes")
    add(f"- SHA-256: `{manifest.sha256}`")
    add(f"- Generated: {report.generated_at_utc.isoformat()}")
    add("")

    failed_gates = report.failed_gates
    warnings = report.warnings
    add("## Verdict")
    add("")
    if failed_gates:
        add(f"**{len(failed_gates)} critical gate(s) failed.** The run is not usable as-is.")
    elif warnings:
        add(f"All critical gates passed. **{len(warnings)} warning(s)** require judgement before use.")
    else:
        add("All critical gates passed with no warnings.")
    add("")
    add(
        "> This status describes *auditable extraction quality*, not accuracy. No general-purpose PDF "
        "parser can guarantee recovery of every visual and semantic relationship, and nothing in this "
        "report should be read as a claim of 100% accuracy."
    )
    add("")

    # --- Checks table ---------------------------------------------------------
    add("## Checks")
    add("")
    add("| Check | Gate | Severity | Result | Summary |")
    add("|---|---|---|---|---|")
    for check in report.checks:
        result = "PASS" if check.passed else "**FAIL**"
        gate = "yes" if check.gate else "—"
        summary = check.summary.replace("|", "\\|")
        add(f"| `{check.check_id}` | {gate} | {check.severity.value} | {result} | {summary} |")
    add("")

    # --- Failures in detail ---------------------------------------------------
    problems = [c for c in report.checks if not c.passed]
    if problems:
        add("## Findings requiring action")
        add("")
        for check in problems:
            add(f"### `{check.check_id}` — {check.title}")
            add("")
            add(f"- **Severity:** {check.severity.value}{' (acceptance gate)' if check.gate else ''}")
            add(f"- **Summary:** {check.summary}")
            if check.threshold:
                add(f"- **Threshold:** `{check.threshold}`")
            if check.remediation:
                add(f"- **Remediation:** {check.remediation}")
            if check.evidence:
                add("- **Evidence:**")
                add("")
                add("```json")
                add(_compact_json(check.evidence))
                add("```")
            add("")

    # --- Tables ---------------------------------------------------------------
    add("## Table findings")
    add("")
    if report.tables:
        add("| # | Label | Page | Rows×Cols | Cells | Empty % | Serialization | Severity |")
        add("|---|---|---|---|---|---|---|---|")
        for t in report.tables:
            add(
                f"| {t.table_index} | {t.detected_label or '—'} | {t.page_no} | {t.num_rows}×{t.num_cols} "
                f"| {t.num_cells} | {t.empty_cell_ratio:.0%} | `{t.serialization}` | {t.severity.value} |"
            )
        add("")
        for t in report.tables:
            if t.notes:
                add(
                    f"- **{t.detected_label or f'Table region {t.table_index}'}** (page {t.page_no}): "
                    + " ".join(t.notes)
                )
        add("")
    else:
        add("No table regions were detected by Docling.")
        add("")

    # --- Pages ----------------------------------------------------------------
    add("## Page coverage")
    add("")
    add(
        "| Page | Src chars | Parsed chars | Char cov. | Token recall | Critical recall | Figures | Review | Severity |"
    )
    add("|---|---|---|---|---|---|---|---|---|")
    source_by_page = {p.page_no: p for p in manifest.pages}
    for row in report.page_coverage:
        src = source_by_page.get(row.page_no)
        figures = src.substantive_image_count if src else 0
        review = f"[link]({row.review_artifact})" if row.review_artifact else "—"
        add(
            f"| {row.page_no} | {row.source_chars} | {row.parsed_chars} | {row.char_coverage:.0%} "
            f"| {row.token_recall:.0%} | {row.critical_token_recall:.0%} | {figures} | {review} "
            f"| {row.severity.value} |"
        )
    add("")

    # --- Furniture ------------------------------------------------------------
    add("## Repeated furniture removed from the body")
    add("")
    if report.furniture_removed:
        add("| Text | Occurrences | Reason |")
        add("|---|---|---|")
        for entry in report.furniture_removed[:20]:
            add(f"| `{str(entry['text'])[:80]}` | {entry['occurrences']} | {entry['reason']} |")
    else:
        add("No body lines were removed by text-based furniture stripping.")
    add("")
    decorative_candidates = [c for c in manifest.furniture_candidates if c.normalized.startswith("image:")]
    text_candidates = [c for c in manifest.furniture_candidates if not c.normalized.startswith("image:")]
    add(
        f"Preflight identified {len(text_candidates)} repeated text furniture pattern(s) and "
        f"{len(decorative_candidates)} repeated image signature(s) "
        f"({manifest.decorative_image_count} decorative image instances in total). Docling additionally "
        f"classified content into its own furniture layer, which the canonical body excludes."
    )
    add("")

    # --- Human review ---------------------------------------------------------
    add("## Human review required")
    add("")
    if report.human_review_items:
        for item in report.human_review_items:
            add(f"- {item}")
    else:
        add("No items flagged for human review.")
    add("")

    return "\n".join(lines) + "\n"


def _compact_json(payload: Any, limit: int = 1800) -> str:
    """Pretty-print evidence, truncating so a report stays readable."""
    import json

    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str)
    if len(text) > limit:
        text = text[:limit] + "\n… (truncated; full evidence in validation/report.json)"
    return text

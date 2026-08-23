"""End-to-end orchestration: preflight → convert → export → validate → manifest.

This is the single entry point that a CLI, a notebook or a future FastAPI worker
all call. It owns sequencing and artifact placement; it owns no parsing logic of
its own, which is what keeps the service boundary clean for a later adapter.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import JsonlLogger, RunDirectory, build_run_manifest
from .config import ParserConfig, Profile
from .domain import RunStatus, SourceManifest, ValidationReport
from .exporters import classify_pictures, export_assets, export_markdown, find_table_labels
from .parser import (
    ConversionFailedError,
    build_inventory,
    convert_pdf,
    page_texts,
    reload_document_json,
    save_document_json,
)
from .pipeline_factory import choose_profile, describe_effective_options, resolve_profile_config
from .preflight import inspect_source, native_page_texts
from .validation.coverage import (
    build_page_coverage,
    coverage_checks,
    document_completeness_check,
)
from .validation.markdown import json_checks, markdown_checks
from .validation.report import build_report, render_markdown_report, write_pages_csv
from .validation.structure import structure_checks, table_checks
from .validation.visual import build_visual_reviews, visual_checks

__all__ = ["RunResult", "run_pipeline"]

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    """Everything a caller needs after a run."""

    run_dir: Path
    status: RunStatus
    report: ValidationReport
    manifest: SourceManifest
    timings: dict[str, float]

    @property
    def exit_code(self) -> int:
        """Non-zero on FAIL, so CI can gate on it."""
        return 1 if self.status is RunStatus.FAIL else 0


def run_pipeline(
    pdf_path: Path | str,
    config: ParserConfig,
    artifacts_base: Path | str = "artifacts",
) -> RunResult:
    """Run the full pipeline and return the outcome.

    Raises:
        PreflightError: if the input is inadmissible.
        ConversionFailedError: if Docling returns no usable document.
    """
    pdf_path = Path(pdf_path)
    timings: dict[str, float] = {}
    warnings: list[str] = []

    # --- 1. Preflight (independent baseline) ---------------------------------
    started = time.perf_counter()
    manifest = inspect_source(pdf_path, config)
    timings["preflight_s"] = time.perf_counter() - started

    # --- 2. Profile decision --------------------------------------------------
    decision = choose_profile(manifest, config)
    effective_config = resolve_profile_config(config, decision.profile)
    logger.info("Profile '%s': %s", decision.profile.value, decision.reason)

    # --- 3. Immutable run directory ------------------------------------------
    run = RunDirectory.create(Path(artifacts_base), pdf_path.stem, manifest.sha256)
    jlog = JsonlLogger(run.path_for("logs/run.jsonl"))
    jlog.log("run_started", source=pdf_path.name, sha256=manifest.sha256,
             profile=decision.profile.value, config_hash=effective_config.config_hash())
    run.write_json("source/manifest.json", manifest.model_dump(mode="json"))
    jlog.log("preflight_complete", pages=manifest.page_count, chars=manifest.total_char_count,
             substantive_images=manifest.substantive_image_count,
             visual_review_pages=manifest.visual_review_pages)

    # --- 4. Conversion --------------------------------------------------------
    started = time.perf_counter()
    try:
        outcome = convert_pdf(pdf_path, effective_config)
    except ConversionFailedError as exc:
        jlog.log("conversion_failed", error=str(exc))
        logger.error("Conversion failed: %s", exc)
        raise
    timings["conversion_s"] = time.perf_counter() - started
    jlog.log("conversion_complete", status=outcome.status, pages=outcome.page_count,
             wall_time_s=outcome.wall_time_s, errors=len(outcome.errors))

    if outcome.is_partial:
        warnings.append(
            f"Docling reported PARTIAL_SUCCESS with {len(outcome.errors)} error item(s); "
            "artifacts represent an incomplete parse."
        )

    document = outcome.document
    inventory = build_inventory(document)

    # --- 5. Canonical JSON ----------------------------------------------------
    started = time.perf_counter()
    json_path = save_document_json(document, run.path_for("docling/document.json"))
    reload_ok, reload_error, roundtrip = _verify_roundtrip(json_path, inventory)
    timings["serialize_json_s"] = time.perf_counter() - started
    jlog.log("json_saved", path=run.relative(json_path), reload_ok=reload_ok, roundtrip=roundtrip)

    # --- 6. Assets + Markdown -------------------------------------------------
    started = time.perf_counter()
    picture_findings = classify_pictures(document, manifest, effective_config)
    asset_paths, page_images = export_assets(document, run, effective_config, picture_findings)

    native_texts = native_page_texts(pdf_path, config)
    table_labels = find_table_labels(document, native_texts)
    logger.info("Labelled tables located: %s",
                {n: f"page {v['page_no']}" for n, v in table_labels.items()})

    export = export_markdown(
        document, run, effective_config, manifest, picture_findings, page_images, table_labels
    )
    timings["export_s"] = time.perf_counter() - started
    jlog.log("export_complete", **export.stats, table_labels={str(k): v for k, v in table_labels.items()})

    # --- 7. Validation --------------------------------------------------------
    started = time.perf_counter()
    parsed_texts = page_texts(document, body_only=True)
    coverage_rows = build_page_coverage(manifest, native_texts, parsed_texts, effective_config)

    page_inv = {p.page_no: p for p in inventory.pages}
    for row in coverage_rows:
        inv = page_inv.get(row.page_no)
        if inv is not None:
            row.has_provenance = inv.has_provenance
            row.pictures = inv.pictures
            row.tables = inv.tables

    reviews = build_visual_reviews(
        document, manifest, coverage_rows, run, effective_config, pdf_path, page_images
    )

    checks = []
    checks += coverage_checks(coverage_rows, manifest, effective_config)
    checks.append(document_completeness_check(manifest, native_texts, parsed_texts, effective_config))
    checks += structure_checks(document, inventory, manifest, picture_findings, effective_config)
    markdown_text = export.markdown_path.read_text(encoding='utf-8')
    checks += table_checks(
        export.table_findings, table_labels, effective_config, markdown_text, run.root
    )
    checks += visual_checks(manifest, coverage_rows, reviews)
    checks += markdown_checks(export.markdown_path, run.root, inventory)
    checks += json_checks(json_path, reload_ok, reload_error, roundtrip)
    checks += _integrity_checks(pdf_path, manifest, outcome)

    report = build_report(
        checks, coverage_rows, export.table_findings, picture_findings,
        manifest, inventory, export.removed_furniture, effective_config,
    )
    run.write_json("validation/report.json", report.model_dump(mode="json"))
    run.write_text("validation/report.md", render_markdown_report(report, manifest, effective_config))
    write_pages_csv(run, coverage_rows, manifest)
    timings["validation_s"] = time.perf_counter() - started
    jlog.log("validation_complete", status=report.status.value,
             failed_gates=[c.check_id for c in report.failed_gates],
             warnings=[c.check_id for c in report.warnings])

    # --- 8. Run manifest ------------------------------------------------------
    docling_info = describe_effective_options(effective_config)
    docling_info["conversion"] = {
        "status": outcome.status,
        "is_partial": outcome.is_partial,
        "errors": outcome.errors[:20],
        "confidence": outcome.confidence,
        "stage_timings_s": outcome.timings,
        "wall_time_s": outcome.wall_time_s,
    }
    if export.synthesized_title:
        warnings.append(
            f"Document had no title item; H1 synthesized from PDF /Title metadata: "
            f"'{export.synthesized_title}'."
        )

    manifest_obj = build_run_manifest(
        run=run,
        source_manifest_data=manifest.model_dump(mode="json"),
        config_hash=effective_config.config_hash(),
        effective_config=effective_config.effective_dict(),
        profile=decision.profile.value,
        profile_reason=decision.reason,
        profile_evidence=decision.evidence,
        docling_info=docling_info,
        timings=timings,
        conversion=docling_info["conversion"],
        status=report.status.value,
        warnings=warnings,
    )
    run.write_json("run_manifest.json", manifest_obj.to_dict())
    jlog.log("run_finished", status=report.status.value, run_dir=run.root.name)

    logger.info("Run complete: %s → %s", report.status.value, run.root)
    return RunResult(run_dir=run.root, status=report.status, report=report,
                     manifest=manifest, timings=timings)


def _verify_roundtrip(json_path: Path, inventory: Any) -> tuple[bool, str | None, dict[str, Any]]:
    """Reload the serialised document and compare inventories."""
    try:
        reloaded = reload_document_json(json_path)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}", {
            "identical": False, "summary": "Reload failed; round-trip not comparable."
        }

    reloaded_inv = build_inventory(reloaded)
    fields = ("page_count", "section_headers", "paragraphs", "list_items", "tables",
              "pictures", "captions", "items_total", "total_char_count")
    diffs = {
        f: {"before": getattr(inventory, f), "after": getattr(reloaded_inv, f)}
        for f in fields
        if getattr(inventory, f) != getattr(reloaded_inv, f)
    }
    identical = not diffs
    summary = (
        "Reloaded document matches the in-memory inventory on all compared fields."
        if identical
        else f"{len(diffs)} field(s) differ after round-trip: {sorted(diffs)}"
    )
    return True, None, {"identical": identical, "summary": summary, "differences": diffs,
                        "compared_fields": list(fields)}


def _integrity_checks(pdf_path: Path, manifest: SourceManifest, outcome: Any) -> list:
    """File-level integrity gates."""
    from .artifacts import sha256_file
    from .domain import CheckResult, Severity

    current = sha256_file(pdf_path)
    checks = [
        CheckResult(
            check_id="source_unmodified",
            title="Source PDF is unchanged by the run",
            passed=current == manifest.sha256,
            severity=Severity.CRITICAL,
            gate=True,
            summary="Source SHA-256 is unchanged after parsing."
            if current == manifest.sha256
            else f"Source hash changed: {manifest.sha256} → {current}",
            evidence={"sha256_before": manifest.sha256, "sha256_after": current,
                      "byte_size": manifest.byte_size},
            threshold={"required": "identical SHA-256"},
            remediation="The parser must never modify its input.",
        ),
        CheckResult(
            check_id="conversion_status",
            title="Docling conversion completed successfully",
            passed=not outcome.is_partial and outcome.status == "success",
            severity=Severity.CRITICAL,
            gate=True,
            summary=f"Conversion status: {outcome.status}"
            + (f" with {len(outcome.errors)} error item(s)" if outcome.errors else ""),
            evidence={"status": outcome.status, "is_partial": outcome.is_partial,
                      "errors": outcome.errors[:5], "wall_time_s": outcome.wall_time_s,
                      "confidence": {k: v for k, v in (outcome.confidence or {}).items()
                                     if k != "pages"}},
            threshold={"required": "ConversionStatus.SUCCESS"},
            remediation="Partial conversions must be quarantined, not published.",
        ),
        CheckResult(
            check_id="expected_page_count",
            title="Parsed page count equals the source page count",
            passed=outcome.page_count == manifest.page_count,
            severity=Severity.CRITICAL,
            gate=True,
            summary=f"{outcome.page_count} parsed vs {manifest.page_count} source pages.",
            evidence={"parsed": outcome.page_count, "source": manifest.page_count},
            threshold={"required": "equal"},
            remediation="A page-count mismatch means pages were dropped during assembly.",
        ),
    ]
    return checks

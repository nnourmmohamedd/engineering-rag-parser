"""Slow full-document acceptance test against the supplied 27-page PDF.

Marked ``slow`` and skipped with an explicit reason when the document is absent
(it is confidential and git-ignored, so a fresh clone skips cleanly).

These assertions encode the acceptance gates. They deliberately assert
*properties* — page count, provenance coverage, no unexplained loss — rather
than hardcoding extracted strings, so the test measures the parser rather than
memorising one output.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from engineering_rag_parser.config import ParserConfig, Profile, load_config
from engineering_rag_parser.domain import RunStatus, Severity
from engineering_rag_parser.pipeline import run_pipeline

from ..conftest import requires_docling_models

pytestmark = [pytest.mark.slow, pytest.mark.integration, requires_docling_models]

EXPECTED_PAGES = 27
EXPECTED_SHA256 = "01e4d6fa3a2e884f83fad507d08b228aa40f814dc0f3c44e6c9db315f73c3b1a"


@pytest.fixture(scope="module")
def acceptance_run(acceptance_pdf: Path, tmp_path_factory: pytest.TempPathFactory):
    """Run the full pipeline once for the whole module (~3 minutes on CPU)."""
    config_path = Path("configs/high_fidelity.yaml")
    cfg = (
        load_config(config_path)
        if config_path.is_file()
        else ParserConfig().with_overrides(profile=Profile.HIGH_FIDELITY)
    )
    return run_pipeline(acceptance_pdf, cfg, tmp_path_factory.mktemp("acceptance"))


class TestGateSourceIntegrity:
    """Gate 1 — the source is the unchanged 27-page PDF."""

    def test_page_count(self, acceptance_run) -> None:
        assert acceptance_run.manifest.page_count == EXPECTED_PAGES

    def test_sha256_matches_supplied_document(self, acceptance_run) -> None:
        assert acceptance_run.manifest.sha256 == EXPECTED_SHA256

    def test_source_is_not_modified(self, acceptance_run) -> None:
        check = _check(acceptance_run, "source_unmodified")
        assert check.passed and check.gate

    def test_document_is_digital_not_scanned(self, acceptance_run) -> None:
        """A text-searchable PDF: OCR must not have been needed."""
        assert acceptance_run.manifest.total_char_count > 20_000
        assert len(acceptance_run.manifest.sparse_pages) < EXPECTED_PAGES // 2


class TestGateConversionAndSerialization:
    """Gates 2-4 — conversion succeeded, JSON reloads, Markdown is usable."""

    def test_conversion_succeeded(self, acceptance_run) -> None:
        assert _check(acceptance_run, "conversion_status").passed

    def test_all_pages_parsed(self, acceptance_run) -> None:
        assert _check(acceptance_run, "expected_page_count").passed

    def test_json_parses_and_reloads(self, acceptance_run) -> None:
        assert _check(acceptance_run, "json_parseable").passed
        assert _check(acceptance_run, "json_reloads_into_model").passed

    def test_json_roundtrip_preserves_inventory(self, acceptance_run) -> None:
        assert _check(acceptance_run, "json_roundtrip_stable").passed

    def test_markdown_is_portable_and_complete(self, acceptance_run) -> None:
        for check_id in (
            "markdown_encoding",
            "markdown_non_empty",
            "markdown_image_links",
            "markdown_no_base64",
            "markdown_no_placeholders",
        ):
            assert _check(acceptance_run, check_id).passed, check_id

    def test_no_broken_asset_references(self, acceptance_run) -> None:
        md = (acceptance_run.run_dir / "markdown" / "document.md").read_text(encoding="utf-8")
        targets = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", md)
        assert targets, "expected referenced image assets"
        for target in targets:
            assert (acceptance_run.run_dir / target).is_file(), target


class TestGateProvenanceAndCoverage:
    """Gates 5, 9, 10 — every page covered, no unexplained loss."""

    def test_every_page_has_provenance(self, acceptance_run) -> None:
        check = _check(acceptance_run, "page_provenance_coverage")
        assert check.passed, check.summary

    def test_page_numbering_is_monotonic(self, acceptance_run) -> None:
        assert _check(acceptance_run, "page_numbering_monotonic").passed

    def test_all_27_pages_are_reported(self, acceptance_run) -> None:
        pages = [row.page_no for row in acceptance_run.report.page_coverage]
        assert pages == list(range(1, EXPECTED_PAGES + 1))

    def test_no_document_level_token_loss(self, acceptance_run) -> None:
        """The gate that matters: no high-information token missing document-wide."""
        check = _check(acceptance_run, "document_text_completeness")
        assert check.passed, check.summary
        assert check.evidence["critical_token_recall"] >= 0.95

    def test_no_duplicated_spans(self, acceptance_run) -> None:
        """OCR was not run over the existing text layer, so nothing should duplicate."""
        assert _check(acceptance_run, "no_duplicated_spans").passed

    def test_no_critical_page_severities_unexplained(self, acceptance_run) -> None:
        critical = [r for r in acceptance_run.report.page_coverage if r.severity is Severity.CRITICAL]
        for row in critical:
            assert row.notes, f"page {row.page_no} is CRITICAL with no explanation"


class TestGateFiguresAndVisualReview:
    """Gates 6, 7 — figures represented, every flagged page reviewed, furniture separated."""

    def test_every_substantive_figure_is_represented(self, acceptance_run) -> None:
        check = _check(acceptance_run, "substantive_figures_represented")
        assert check.passed, check.summary

    def test_every_flagged_page_has_a_review_artifact(self, acceptance_run) -> None:
        check = _check(acceptance_run, "visual_review_coverage")
        assert check.passed, check.summary
        for page_no in acceptance_run.manifest.visual_review_pages:
            assert (acceptance_run.run_dir / f"validation/review/page{page_no:03d}.html").is_file()

    def test_decorative_furniture_is_separated_from_diagrams(self, acceptance_run) -> None:
        manifest = acceptance_run.manifest
        assert manifest.decorative_image_count > manifest.substantive_image_count, (
            "the repeated banner/watermark should dominate the raw image count"
        )
        assert manifest.substantive_image_count > 0

    def test_furniture_does_not_pollute_the_body(self, acceptance_run) -> None:
        """The website/page-number footer must not appear in the canonical body."""
        md = (acceptance_run.run_dir / "markdown" / "document.md").read_text(encoding="utf-8")
        assert not re.search(r"Page \d+ of 27", md), "page-number furniture leaked into the body"

    def test_page_anchors_present_for_citation(self, acceptance_run) -> None:
        md = (acceptance_run.run_dir / "markdown" / "document.md").read_text(encoding="utf-8")
        anchors = re.findall(r"<!-- page: (\d+) -->", md)
        assert len(anchors) == EXPECTED_PAGES
        assert [int(a) for a in anchors] == sorted(int(a) for a in anchors)


class TestGateTables:
    """Gate 8 — Tables 1, 2 and 3 located and individually reported."""

    def test_three_labelled_tables_are_located(self, acceptance_run) -> None:
        check = _check(acceptance_run, "labelled_tables_located")
        assert check.passed, check.summary
        located = check.evidence["tables"]
        assert {1, 2, 3} <= {int(k) for k in located}

    def test_each_labelled_table_reports_a_page_and_title(self, acceptance_run) -> None:
        located = _located_tables(acceptance_run)
        for number in (1, 2, 3):
            entry = located[number]
            assert entry["page_no"] is not None, f"Table {number} has no page"
            assert entry["title"], f"Table {number} has no title"
            assert entry["outcome"], f"Table {number} has no reported outcome"

    def test_table_numbering_is_not_assumed_to_follow_pages(self, acceptance_run) -> None:
        """Verifies the located pages come from evidence, not from an ordering assumption."""
        located = _located_tables(acceptance_run)
        pages = [located[n]["page_no"] for n in (1, 2, 3)]
        assert len(set(pages)) == 3

    def test_a_table_detected_as_a_picture_is_still_accounted_for(self, acceptance_run) -> None:
        """Docling may classify a raster table as a picture; it must not go unreported."""
        for entry in _located_tables(acceptance_run).values():
            if entry["docling_regions"] == 0:
                assert entry["covered_by_picture_regions"], (
                    f"table on page {entry['page_no']} has neither a table region nor a picture region"
                )

    def test_unrecovered_tables_are_preserved_and_flagged(self, acceptance_run) -> None:
        """The no-silent-loss gate: unreadable content must leave an asset and a warning."""
        check = _check(acceptance_run, "unrecovered_content_preserved")
        assert check.passed, check.summary
        for region in check.evidence["regions"]:
            assert region["asset_exists"], region
            assert region["warning_in_markdown"], region

    def test_every_table_has_an_individual_finding(self, acceptance_run) -> None:
        for finding in acceptance_run.report.tables:
            assert finding.serialization in {"markdown", "html", "asset_only"}
            if finding.serialization == "asset_only":
                assert finding.notes, "an unrecovered table must carry an explanation"


class TestGateArtifactsAndStatus:
    """Gates 11-12 — artifacts complete, status honest."""

    def test_status_is_not_fail(self, acceptance_run) -> None:
        assert acceptance_run.status in (RunStatus.PASS, RunStatus.PASS_WITH_WARNINGS), (
            f"failed gates: {[c.check_id for c in acceptance_run.report.failed_gates]}"
        )

    def test_exit_code_matches_status(self, acceptance_run) -> None:
        assert acceptance_run.exit_code == (1 if acceptance_run.status is RunStatus.FAIL else 0)

    def test_canonical_artifact_tree(self, acceptance_run) -> None:
        for rel in (
            "run_manifest.json",
            "source/manifest.json",
            "docling/document.json",
            "markdown/document.md",
            "markdown/document.raw.md",
            "validation/report.json",
            "validation/report.md",
            "validation/pages.csv",
            "logs/run.jsonl",
        ):
            assert (acceptance_run.run_dir / rel).is_file(), rel

    def test_run_manifest_records_reproduction_facts(self, acceptance_run) -> None:
        manifest = json.loads((acceptance_run.run_dir / "run_manifest.json").read_text(encoding="utf-8"))
        assert manifest["source"]["sha256"] == EXPECTED_SHA256
        assert manifest["source"]["page_count"] == EXPECTED_PAGES
        assert manifest["docling"]["versions"]["docling"]
        assert manifest["config_hash"]
        assert manifest["profile_reason"]
        assert len(manifest["artifacts"]) > 40

    def test_warnings_carry_human_review_items(self, acceptance_run) -> None:
        """PASS_WITH_WARNINGS must be actionable, not a bare label."""
        if acceptance_run.status is RunStatus.PASS_WITH_WARNINGS:
            assert acceptance_run.report.human_review_items

    def test_pages_csv_has_a_row_per_page(self, acceptance_run) -> None:
        lines = (
            (acceptance_run.run_dir / "validation" / "pages.csv")
            .read_text(encoding="utf-8")
            .strip()
            .split("\n")
        )
        assert len(lines) == EXPECTED_PAGES + 1  # header + one row per page


def _located_tables(run_result) -> dict[int, dict]:
    """Table evidence keyed by int.

    The in-memory ``CheckResult`` keeps integer table numbers; only the JSON
    round-trip stringifies them. Normalising here lets the assertions read the
    same whether the report came from memory or from disk.
    """
    evidence = _check(run_result, "labelled_tables_located").evidence["tables"]
    return {int(k): v for k, v in evidence.items()}


def _check(run_result, check_id: str):
    """Fetch a single check from a run, failing clearly if it is absent."""
    for check in run_result.report.checks:
        if check.check_id == check_id:
            return check
    raise AssertionError(
        f"check {check_id!r} not found; available: {sorted(c.check_id for c in run_result.report.checks)}"
    )

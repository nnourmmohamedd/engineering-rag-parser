"""Unit tests for the validation framework: status logic, coverage and QA checks."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from engineering_rag_parser.config import ParserConfig
from engineering_rag_parser.domain import (
    CheckResult,
    DocumentInventory,
    RunStatus,
    Severity,
    SourceManifest,
    SourcePage,
    ValidationReport,
)
from engineering_rag_parser.validation.coverage import (
    build_page_coverage,
    coverage_checks,
    document_completeness_check,
    strip_furniture,
)
from engineering_rag_parser.validation.markdown import markdown_checks


def _check(check_id: str, passed: bool, severity: Severity, gate: bool = False) -> CheckResult:
    return CheckResult(check_id=check_id, title=check_id, passed=passed, severity=severity, gate=gate)


def _report(*checks: CheckResult) -> ValidationReport:
    return ValidationReport(
        status=RunStatus.FAIL, generated_at_utc=datetime.now(timezone.utc), checks=list(checks)
    )


class TestStatusLogic:
    def test_all_pass_is_pass(self) -> None:
        report = _report(_check("a", True, Severity.CRITICAL, gate=True))
        assert report.compute_status(strict=False) is RunStatus.PASS

    def test_warning_is_pass_with_warnings(self) -> None:
        report = _report(_check("a", False, Severity.WARNING))
        assert report.compute_status(strict=False) is RunStatus.PASS_WITH_WARNINGS

    def test_warning_fails_in_strict_mode(self) -> None:
        report = _report(_check("a", False, Severity.WARNING))
        assert report.compute_status(strict=True) is RunStatus.FAIL

    def test_critical_failure_is_fail(self) -> None:
        report = _report(_check("a", False, Severity.CRITICAL, gate=True))
        assert report.compute_status(strict=False) is RunStatus.FAIL

    def test_critical_beats_warning(self) -> None:
        report = _report(_check("a", False, Severity.WARNING), _check("b", False, Severity.CRITICAL))
        assert report.compute_status(strict=False) is RunStatus.FAIL

    def test_failed_info_check_does_not_change_status(self) -> None:
        report = _report(_check("a", False, Severity.INFO))
        assert report.compute_status(strict=False) is RunStatus.PASS

    def test_failed_gates_property(self) -> None:
        report = _report(
            _check("gated", False, Severity.CRITICAL, gate=True),
            _check("ungated", False, Severity.WARNING),
        )
        assert [c.check_id for c in report.failed_gates] == ["gated"]
        assert [c.check_id for c in report.warnings] == ["ungated"]


class TestStripFurniture:
    def test_removes_matching_lines_and_counts_chars(self) -> None:
        from engineering_rag_parser.normalization import normalize_line

        keys = {normalize_line("www.example.com    Page 1 of 27")}
        text = "Body sentence.\nwww.example.com    Page 5 of 27\nMore body."
        kept, removed = strip_furniture(text, keys)
        assert "Page" not in kept
        assert "Body sentence." in kept and "More body." in kept
        assert removed > 0

    def test_no_keys_is_a_noop(self) -> None:
        assert strip_furniture("anything", set()) == ("anything", 0)


def _manifest(pages: int = 3, **page_kwargs: object) -> SourceManifest:
    return SourceManifest(
        filename="t.pdf",
        byte_size=100,
        sha256="a" * 64,
        mime_guess="application/pdf",
        magic_ok=True,
        page_count=pages,
        pages=[
            SourcePage(
                page_no=i,
                width_pt=596.0,
                height_pt=842.0,
                char_count=500,
                text_sha256="b" * 64,
                **page_kwargs,  # type: ignore[arg-type]
            )
            for i in range(1, pages + 1)
        ],
        generated_at_utc=datetime.now(timezone.utc),
    )


class TestPageCoverage:
    def test_perfect_match_scores_one(self) -> None:
        text = "The transmitter FT-101 provides a 4-20 mA signal at 24 V DC per ISA-5.1."
        rows = build_page_coverage(_manifest(1), {1: text}, {1: text}, ParserConfig())
        assert rows[0].char_coverage == 1.0
        assert rows[0].token_recall == 1.0
        assert rows[0].critical_token_recall == 1.0
        assert rows[0].severity is Severity.INFO

    def test_detects_genuine_loss(self) -> None:
        # Must exceed sparse_text_char_threshold (200) or the text-quality
        # thresholds deliberately do not engage — a short page is judged visually.
        native = (
            "The transmitter FT-101 provides a 4-20 mA signal at 24 V DC per ISA-5.1 standard. "
            "The loop is rated SIL 2 and the P&ID shows the interlock to PT-202 at 16 bar. "
            "Calibration is verified against the instrument index before commissioning begins."
        )
        parsed = "The transmitter provides a signal. The loop is rated and the drawing shows the interlock."
        rows = build_page_coverage(_manifest(1), {1: native}, {1: parsed}, ParserConfig())
        assert rows[0].source_chars >= ParserConfig().thresholds.sparse_text_char_threshold
        assert rows[0].critical_token_recall < 1.0
        assert "FT-101" in rows[0].missing_critical_tokens
        assert rows[0].severity is Severity.CRITICAL

    def test_short_page_is_not_judged_on_text_thresholds(self) -> None:
        """Below the sparse threshold, text metrics are recorded but must not gate."""
        rows = build_page_coverage(_manifest(1), {1: "FT-101 at 24 V DC."}, {1: ""}, ParserConfig())
        assert rows[0].severity is Severity.INFO

    def test_cross_page_content_counts_as_relocated_not_lost(self) -> None:
        """A paragraph crossing a page break is attributed to the page it starts on.

        That is correct reading-order repair and must not be reported as loss.
        """
        native = {1: "", 2: "The AVEVA E&I model integrates with AutoCAD Plant 3D for routing."}
        parsed = {1: "The AVEVA E&I model integrates with AutoCAD Plant 3D for routing.", 2: ""}
        rows = build_page_coverage(_manifest(2), native, parsed, ParserConfig())
        page2 = rows[1]
        assert page2.missing_critical_tokens == []
        assert "AVEVA" in page2.relocated_critical_tokens
        assert page2.critical_token_recall == 1.0

    def test_document_check_catches_true_loss(self) -> None:
        native = {1: "Rated SIL 3 with a 4-20 mA loop.", 2: "Uses AVEVA E&I tooling."}
        parsed = {1: "Rated SIL 3 with a 4-20 mA loop.", 2: ""}
        result = document_completeness_check(_manifest(2), native, parsed, ParserConfig())
        assert result.passed is False
        assert result.gate is True
        assert "AVEVA" in result.evidence["missing_critical_tokens"]

    def test_document_check_passes_on_relocation(self) -> None:
        native = {1: "", 2: "Uses AVEVA E&I tooling at 24 V DC."}
        parsed = {1: "Uses AVEVA E&I tooling at 24 V DC.", 2: ""}
        assert document_completeness_check(_manifest(2), native, parsed, ParserConfig()).passed

    def test_sparse_page_is_not_judged_on_text(self) -> None:
        manifest = _manifest(1)
        manifest.pages[0].char_count = 30
        manifest.pages[0].is_sparse_text = True
        rows = build_page_coverage(manifest, {1: "A few words."}, {1: ""}, ParserConfig())
        assert rows[0].severity is Severity.INFO
        assert any("not evidence of" in n for n in rows[0].notes)

    def test_duplicated_span_raises_warning(self) -> None:
        dup = "This exact sentence occurs twice on the page. This exact sentence occurs twice on the page."
        rows = build_page_coverage(_manifest(1), {1: dup}, {1: dup}, ParserConfig())
        assert rows[0].duplicated_spans
        assert rows[0].severity is Severity.WARNING


class TestCoverageChecks:
    def test_missing_page_fails_gate(self) -> None:
        rows = build_page_coverage(_manifest(3), {1: "x"}, {1: "x"}, ParserConfig())
        rows.pop()  # simulate a dropped page
        checks = {c.check_id: c for c in coverage_checks(rows, _manifest(3), ParserConfig())}
        assert checks["page_count_match"].passed is False
        assert checks["page_count_match"].gate is True

    def test_provenance_gap_fails_gate(self) -> None:
        rows = build_page_coverage(_manifest(2), {1: "x", 2: "y"}, {1: "x", 2: "y"}, ParserConfig())
        rows[0].has_provenance = True
        rows[1].has_provenance = False
        checks = {c.check_id: c for c in coverage_checks(rows, _manifest(2), ParserConfig())}
        assert checks["page_provenance_coverage"].passed is False
        assert 2 in checks["page_provenance_coverage"].evidence["pages_without_provenance"]


class TestMarkdownChecks:
    def _run(self, tmp_path: Path, content: str, inventory: DocumentInventory | None = None):
        md = tmp_path / "document.md"
        md.write_bytes(content.encode("utf-8"))
        inv = inventory or DocumentInventory(section_headers=1)
        return {c.check_id: c for c in markdown_checks(md, tmp_path, inv)}

    def test_clean_document_passes(self, tmp_path: Path) -> None:
        (tmp_path / "img.png").write_bytes(b"\x89PNG\r\n")
        content = "# Title\n\n## Section 1\n\n" + ("Body text about FT-101. " * 30) + "\n\n![fig](img.png)\n"
        checks = self._run(tmp_path, content)
        for cid in (
            "markdown_encoding",
            "markdown_non_empty",
            "markdown_image_links",
            "markdown_no_base64",
            "markdown_no_placeholders",
        ):
            assert checks[cid].passed, f"{cid} failed: {checks[cid].summary}"

    def test_crlf_fails(self, tmp_path: Path) -> None:
        checks = self._run(tmp_path, "# Title\r\n\r\n" + "body " * 200)
        assert checks["markdown_encoding"].passed is False

    def test_broken_image_link_fails_gate(self, tmp_path: Path) -> None:
        checks = self._run(tmp_path, "# T\n\n" + "body " * 200 + "\n\n![x](missing.png)\n")
        assert checks["markdown_image_links"].passed is False
        assert checks["markdown_image_links"].gate is True

    def test_absolute_path_is_non_portable(self, tmp_path: Path) -> None:
        checks = self._run(tmp_path, "# T\n\n" + "body " * 200 + "\n\n![x](C:/tmp/a.png)\n")
        assert checks["markdown_image_links"].passed is False

    def test_base64_is_rejected(self, tmp_path: Path) -> None:
        checks = self._run(tmp_path, "# T\n\n" + "body " * 200 + "\n\n![x](data:image/png;base64,AAAA)\n")
        assert checks["markdown_no_base64"].passed is False

    def test_internal_marker_is_rejected(self, tmp_path: Path) -> None:
        checks = self._run(tmp_path, "# T\n\n" + "body " * 200 + "\n\n<!--ERP:TABLE:0-->\n")
        assert checks["markdown_no_placeholders"].passed is False

    def test_page_anchor_is_not_a_placeholder(self, tmp_path: Path) -> None:
        """The legitimate provenance anchor must not trip the placeholder check."""
        checks = self._run(tmp_path, "# T\n\n<!-- page: 3 -->\n\n" + "body " * 200)
        assert checks["markdown_no_placeholders"].passed is True

    def test_ragged_table_is_flagged(self, tmp_path: Path) -> None:
        table = "| a | b |\n| --- | --- |\n| 1 | 2 | 3 |\n"
        checks = self._run(tmp_path, "# T\n\n" + "body " * 200 + "\n\n" + table)
        assert checks["markdown_table_consistency"].passed is False

    def test_consistent_table_passes(self, tmp_path: Path) -> None:
        table = "| a | b |\n| --- | --- |\n| 1 | 2 |\n"
        checks = self._run(tmp_path, "# T\n\n" + "body " * 200 + "\n\n" + table)
        assert checks["markdown_table_consistency"].passed is True

    def test_multiple_h1_is_flagged(self, tmp_path: Path) -> None:
        checks = self._run(tmp_path, "# One\n\n# Two\n\n" + "body " * 200)
        assert checks["markdown_heading_structure"].passed is False

    def test_empty_document_fails(self, tmp_path: Path) -> None:
        checks = self._run(tmp_path, "# T\n")
        assert checks["markdown_non_empty"].passed is False

"""Unit tests for picture classification, furniture stripping and Markdown post-processing."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from engineering_rag_parser.config import ParserConfig
from engineering_rag_parser.domain import (
    FurnitureCandidate,
    PictureFinding,
    Severity,
    SourceManifest,
    SourcePage,
)
from engineering_rag_parser.exporters import (
    _normalize_whitespace,
    _overlap_fraction,
    _strip_repeated_furniture_lines,
    flag_table_only_pictures,
)
from engineering_rag_parser.normalization import normalize_line
from engineering_rag_parser.parser import _portabalize_json_uris
from engineering_rag_parser.preflight import PreflightError, inspect_source


class TestOverlapFraction:
    def test_fully_contained(self) -> None:
        assert _overlap_fraction((10, 10, 20, 20), (0, 0, 100, 100)) == 1.0

    def test_disjoint(self) -> None:
        assert _overlap_fraction((0, 0, 10, 10), (50, 50, 60, 60)) == 0.0

    def test_half_contained(self) -> None:
        assert _overlap_fraction((0, 0, 10, 10), (5, 0, 100, 100)) == pytest.approx(0.5)

    def test_touching_edges_is_zero(self) -> None:
        assert _overlap_fraction((0, 0, 10, 10), (10, 0, 20, 10)) == 0.0

    def test_zero_area_inner(self) -> None:
        assert _overlap_fraction((5, 5, 5, 5), (0, 0, 10, 10)) == 0.0


class TestNormalizeWhitespace:
    def test_collapses_justification_runs(self) -> None:
        assert _normalize_whitespace("These  deliverables   define  the scope.") == (
            "These deliverables define the scope.\n"
        )

    def test_preserves_list_indentation(self) -> None:
        """Leading indentation carries list nesting and must survive."""
        assert _normalize_whitespace("- a\n    - b  c") == "- a\n    - b c\n"

    def test_leaves_table_rows_untouched(self) -> None:
        assert _normalize_whitespace("| a  b | c |") == "| a  b | c |\n"

    def test_leaves_fenced_code_untouched(self) -> None:
        text = "```\nx   =   1\n```"
        assert _normalize_whitespace(text) == "```\nx   =   1\n```\n"

    def test_collapses_excess_blank_lines(self) -> None:
        assert _normalize_whitespace("a\n\n\n\n\nb") == "a\n\nb\n"

    def test_ends_with_single_newline(self) -> None:
        assert _normalize_whitespace("text").endswith("\n")
        assert not _normalize_whitespace("text").endswith("\n\n")

    def test_does_not_damage_html_block(self) -> None:
        assert _normalize_whitespace("<td>a  b</td>") == "<td>a  b</td>\n"


def _manifest_with_furniture() -> SourceManifest:
    footer = "www.example.com    Page 1 of 27"
    return SourceManifest(
        filename="t.pdf",
        byte_size=1,
        sha256="a" * 64,
        mime_guess="application/pdf",
        magic_ok=True,
        page_count=1,
        pages=[SourcePage(page_no=1, width_pt=596, height_pt=842, text_sha256="b" * 64)],
        furniture_candidates=[
            FurnitureCandidate(
                text=footer,
                normalized=normalize_line(footer),
                pages=[1, 2, 3],
                page_fraction=1.0,
                band="footer",
                kind="page_number",
            )
        ],
        generated_at_utc=datetime.now(timezone.utc),
    )


class TestFurnitureStripping:
    def test_removes_repeated_footer_lines(self) -> None:
        markdown = "Body one.\nwww.example.com    Page 7 of 27\nBody two.\n"
        out, evidence = _strip_repeated_furniture_lines(markdown, _manifest_with_furniture(), ParserConfig())
        assert "Page 7 of 27" not in out
        assert "Body one." in out and "Body two." in out
        assert evidence and evidence[0]["occurrences"] == 1

    def test_records_evidence_for_every_removal(self) -> None:
        markdown = "\n".join(f"www.example.com    Page {i} of 27" for i in range(1, 4))
        _out, evidence = _strip_repeated_furniture_lines(markdown, _manifest_with_furniture(), ParserConfig())
        assert sum(e["occurrences"] for e in evidence) == 3

    def test_disabled_by_config(self) -> None:
        cfg = ParserConfig()
        cfg = cfg.model_copy(
            update={"export": cfg.export.model_copy(update={"remove_repeated_furniture_text": False})}
        )
        markdown = "www.example.com    Page 7 of 27\n"
        out, evidence = _strip_repeated_furniture_lines(markdown, _manifest_with_furniture(), cfg)
        assert out == markdown
        assert evidence == []

    def test_body_text_is_never_removed(self) -> None:
        markdown = "A normal body sentence that happens to mention page 7 of the manual.\n"
        out, _ = _strip_repeated_furniture_lines(markdown, _manifest_with_furniture(), ParserConfig())
        assert "normal body sentence" in out


class TestPreflightSafety:
    def test_rejects_non_pdf(self, tmp_path: Path) -> None:
        path = tmp_path / "fake.pdf"
        path.write_bytes(b"NOT A PDF AT ALL")
        with pytest.raises(PreflightError, match="does not begin with"):
            inspect_source(path, ParserConfig())

    def test_rejects_oversized_file(self, tmp_path: Path) -> None:
        path = tmp_path / "big.pdf"
        path.write_bytes(b"%PDF-1.4\n" + b"0" * 2048)
        cfg = ParserConfig()
        cfg = cfg.model_copy(update={"limits": cfg.limits.model_copy(update={"max_file_size_mb": 0.001})})
        with pytest.raises(PreflightError, match="max_file_size_mb"):
            inspect_source(path, cfg)

    def test_rejects_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(PreflightError, match="not a file"):
            inspect_source(tmp_path / "absent.pdf", ParserConfig())


@pytest.mark.usefixtures("structured_pdf")
class TestPreflightOnSyntheticPdf:
    def test_reports_pages_and_text(self, structured_pdf: Path, config: ParserConfig) -> None:
        manifest = inspect_source(structured_pdf, config)
        assert manifest.page_count == 3
        assert manifest.total_char_count > 200
        assert manifest.magic_ok is True
        assert manifest.is_encrypted is False

    def test_hash_is_stable_and_file_untouched(self, structured_pdf: Path, config: ParserConfig) -> None:
        before = structured_pdf.read_bytes()
        first = inspect_source(structured_pdf, config)
        second = inspect_source(structured_pdf, config)
        assert first.sha256 == second.sha256
        assert structured_pdf.read_bytes() == before

    def test_detects_repeated_footer_furniture(self, structured_pdf: Path, config: ParserConfig) -> None:
        manifest = inspect_source(structured_pdf, config)
        kinds = {c.kind for c in manifest.furniture_candidates}
        assert kinds & {"page_number", "website", "header", "footer"}

    def test_finds_the_figure_as_substantive(self, structured_pdf: Path, config: ParserConfig) -> None:
        manifest = inspect_source(structured_pdf, config)
        assert manifest.substantive_image_count >= 1
        assert 3 in manifest.pages_with_substantive_images

    def test_text_samples_are_redacted(self, structured_pdf: Path, config: ParserConfig) -> None:
        manifest = inspect_source(structured_pdf, config)
        for page in manifest.pages:
            assert len(page.text_sample) <= config.text_sample_chars + 1

    def test_records_tool_versions(self, structured_pdf: Path, config: ParserConfig) -> None:
        manifest = inspect_source(structured_pdf, config)
        assert {"pypdf", "pdfminer.six", "pypdfium2"} <= set(manifest.tools)


class TestPreflightEdgeCases:
    def test_image_only_page_is_flagged_for_review(self, image_only_pdf: Path, config: ParserConfig) -> None:
        manifest = inspect_source(image_only_pdf, config)
        assert manifest.pages[0].is_sparse_text is True
        assert manifest.pages[0].needs_visual_review is True
        assert 1 in manifest.visual_review_pages

    def test_rotation_is_recorded(self, rotated_pdf: Path, config: ParserConfig) -> None:
        manifest = inspect_source(rotated_pdf, config)
        assert manifest.page_count == 2
        assert any(p.rotation for p in manifest.pages)

    def test_small_figure_still_needs_review(self, image_only_pdf: Path, config: ParserConfig) -> None:
        """Review is presence-driven, so a modest figure cannot slip past an area threshold."""
        cfg = config.model_copy(
            update={"thresholds": config.thresholds.model_copy(update={"image_heavy_area_fraction": 0.99})}
        )
        manifest = inspect_source(image_only_pdf, cfg)
        assert manifest.pages[0].is_image_heavy is False
        assert manifest.pages[0].needs_visual_review is True


def _picture(
    caption: str, classification: str = "substantive", asset_path: str | None = "a.png"
) -> PictureFinding:
    return PictureFinding(
        picture_index=0,
        self_ref="#/pictures/0",
        page_no=5,
        caption=caption,
        classification=classification,  # type: ignore[arg-type]
        asset_path=asset_path,
    )


class TestFlagTableOnlyPictures:
    """Regression tests for D-5: a labelled table whose body is a *picture*, not a table region."""

    def test_flags_substantive_picture_whose_caption_names_a_known_table(self) -> None:
        findings = [_picture("Table 3: Installation Drawings")]
        flag_table_only_pictures(findings, {3: {"page_no": 5, "title": "Installation Drawings"}})
        assert findings[0].represents_table_label == "Table 3"
        assert findings[0].severity is Severity.CRITICAL
        assert any("Table 3" in n for n in findings[0].notes)

    def test_ignores_unrelated_caption(self) -> None:
        findings = [_picture("Figure 1: Loop diagram")]
        flag_table_only_pictures(findings, {3: {"page_no": 5, "title": "x"}})
        assert findings[0].represents_table_label is None

    def test_ignores_decorative_pictures_even_with_matching_caption(self) -> None:
        findings = [_picture("Table 3: Installation Drawings", classification="decorative_repeated")]
        flag_table_only_pictures(findings, {3: {"page_no": 5, "title": "x"}})
        assert findings[0].represents_table_label is None

    def test_ignores_a_table_number_not_in_the_located_labels(self) -> None:
        findings = [_picture("Table 9: Unrelated")]
        flag_table_only_pictures(findings, {3: {"page_no": 5, "title": "x"}})
        assert findings[0].represents_table_label is None


class TestPortabalizeJsonUris:
    """Regression tests for D-3: Windows backslash separators in JSON `"uri"` values."""

    def test_normalizes_windows_separator(self) -> None:
        text = '{"uri": "assets\\\\image_000.png"}'
        out = _portabalize_json_uris(text)
        assert out == '{"uri": "assets/image_000.png"}'

    def test_leaves_forward_slash_paths_untouched(self) -> None:
        text = '{"uri": "assets/image_000.png"}'
        assert _portabalize_json_uris(text) == text

    def test_leaves_remote_urls_untouched(self) -> None:
        text = '{"uri": "https://example.com/a.png"}'
        assert _portabalize_json_uris(text) == text

    def test_normalizes_multiple_occurrences(self) -> None:
        text = '{"a": {"uri": "x\\\\y.png"}, "b": {"uri": "p\\\\q.png"}}'
        out = _portabalize_json_uris(text)
        assert "\\\\" not in out
        assert '"uri": "x/y.png"' in out
        assert '"uri": "p/q.png"' in out

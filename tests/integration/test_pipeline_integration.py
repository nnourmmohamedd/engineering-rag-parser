"""Integration tests: real Docling conversion on small synthetic fixtures.

These exercise the whole pipeline without the confidential acceptance document,
so CI can run them. They are marked ``integration`` and skip automatically when
Docling model weights are not cached.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engineering_rag_parser.config import ParserConfig, Profile
from engineering_rag_parser.domain import RunStatus
from engineering_rag_parser.pipeline import run_pipeline
from engineering_rag_parser.pipeline_factory import (
    build_converter,
    build_pipeline_options,
    choose_profile,
    describe_effective_options,
    docling_versions,
    resolve_profile_config,
)

from ..conftest import requires_docling_models

pytestmark = pytest.mark.integration


class TestPipelineFactory:
    """These need no model weights — they only build option objects."""

    def test_default_disables_ocr(self) -> None:
        assert build_pipeline_options(ParserConfig()).do_ocr is False

    def test_high_fidelity_uses_accurate_tables(self) -> None:
        cfg = resolve_profile_config(ParserConfig(), Profile.HIGH_FIDELITY)
        options = build_pipeline_options(cfg)
        assert options.table_structure_options.mode.value == "accurate"
        assert options.generate_picture_images is True
        assert options.images_scale >= 2.0

    def test_scanned_enables_full_page_ocr(self) -> None:
        cfg = resolve_profile_config(ParserConfig(), Profile.SCANNED)
        options = build_pipeline_options(cfg)
        assert options.do_ocr is True
        # Current API is OcrMode.FULL_PAGE; force_full_page_ocr is deprecated.
        assert options.ocr_options.mode.value == "full_page"

    def test_remote_services_always_disabled(self) -> None:
        assert build_pipeline_options(ParserConfig()).enable_remote_services is False

    def test_unknown_backend_raises(self) -> None:
        cfg = ParserConfig()
        bad = cfg.model_copy(update={"docling": cfg.docling.model_copy(update={"backend": "nope"})})
        with pytest.raises(ValueError, match="Unknown PDF backend"):
            build_converter(bad)

    def test_versions_are_resolved_not_unknown(self) -> None:
        versions = docling_versions()
        assert versions["docling"] not in ("unknown", "not-installed")
        assert versions["docling-core"] not in ("unknown", "not-installed")

    def test_effective_options_are_serialisable(self) -> None:
        json.dumps(describe_effective_options(ParserConfig()))


class TestAutoProfile:
    def test_picks_high_fidelity_for_digital_text_with_figures(
        self, structured_pdf: Path, config: ParserConfig
    ) -> None:
        from engineering_rag_parser.preflight import inspect_source

        manifest = inspect_source(structured_pdf, config)
        decision = choose_profile(manifest, config.with_overrides(profile=Profile.AUTO))
        assert decision.profile is Profile.HIGH_FIDELITY
        assert "figure" in decision.reason
        assert decision.evidence["page_count"] == 3

    def test_picks_scanned_for_image_only(self, image_only_pdf: Path, config: ParserConfig) -> None:
        from engineering_rag_parser.preflight import inspect_source

        manifest = inspect_source(image_only_pdf, config)
        decision = choose_profile(manifest, config.with_overrides(profile=Profile.AUTO))
        assert decision.profile is Profile.SCANNED
        assert "OCR is required" in decision.reason

    def test_explicit_profile_is_respected_but_evidence_recorded(
        self, structured_pdf: Path, config: ParserConfig
    ) -> None:
        from engineering_rag_parser.preflight import inspect_source

        manifest = inspect_source(structured_pdf, config)
        decision = choose_profile(manifest, config.with_overrides(profile=Profile.DEFAULT))
        assert decision.profile is Profile.DEFAULT
        assert "explicitly" in decision.reason
        assert decision.evidence["chars_per_page"] > 0


@requires_docling_models
class TestEndToEndOnSyntheticPdf:
    @pytest.fixture(scope="class")
    @classmethod
    def run_result(cls, structured_pdf: Path, tmp_path_factory: pytest.TempPathFactory):
        artifacts = tmp_path_factory.mktemp("artifacts")
        cfg = ParserConfig().with_overrides(profile=Profile.HIGH_FIDELITY)
        return run_pipeline(structured_pdf, cfg, artifacts), artifacts

    def test_status_is_not_fail(self, run_result) -> None:
        result, _ = run_result
        assert result.status in (RunStatus.PASS, RunStatus.PASS_WITH_WARNINGS), (
            f"Unexpected FAIL. Failed gates: {[c.check_id for c in result.report.failed_gates]}"
        )

    def test_canonical_artifacts_exist(self, run_result) -> None:
        result, _ = run_result
        for rel in ("run_manifest.json", "source/manifest.json", "docling/document.json",
                    "markdown/document.md", "validation/report.json", "validation/report.md",
                    "validation/pages.csv", "logs/run.jsonl"):
            assert (result.run_dir / rel).is_file(), f"missing artifact: {rel}"

    def test_json_reloads_into_docling_model(self, run_result) -> None:
        from docling_core.types.doc import DoclingDocument

        result, _ = run_result
        doc = DoclingDocument.load_from_json(result.run_dir / "docling" / "document.json")
        assert len(doc.pages) == 3

    def test_markdown_is_utf8_lf_and_has_content(self, run_result) -> None:
        result, _ = run_result
        raw = (result.run_dir / "markdown" / "document.md").read_bytes()
        assert b"\r" not in raw
        text = raw.decode("utf-8")
        assert "FT-101" in text, "instrument tag must survive extraction"
        assert "4-20 mA" in text or "4-20" in text

    def test_no_base64_in_markdown(self, run_result) -> None:
        result, _ = run_result
        assert "base64," not in (result.run_dir / "markdown" / "document.md").read_text(encoding="utf-8")

    def test_image_links_resolve(self, run_result) -> None:
        import re

        result, _ = run_result
        text = (result.run_dir / "markdown" / "document.md").read_text(encoding="utf-8")
        for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", text):
            assert (result.run_dir / match.group(1)).is_file(), f"broken link {match.group(1)}"

    def test_run_manifest_is_complete(self, run_result) -> None:
        result, _ = run_result
        manifest = json.loads((result.run_dir / "run_manifest.json").read_text(encoding="utf-8"))
        for key in ("run_id", "parser_version", "config_hash", "effective_config", "profile",
                    "profile_reason", "docling", "environment", "timings_s", "artifacts", "status"):
            assert key in manifest, f"run manifest missing {key}"
        assert manifest["source"]["page_count"] == 3
        assert len(manifest["artifacts"]) > 5

    def test_manifest_has_no_absolute_paths(self, run_result) -> None:
        result, _ = run_result
        blob = (result.run_dir / "run_manifest.json").read_text(encoding="utf-8")
        assert "C:\\\\" not in blob and "/home/" not in blob

    def test_source_pdf_is_unmodified(self, run_result, structured_pdf: Path) -> None:
        result, _ = run_result
        check = next(c for c in result.report.checks if c.check_id == "source_unmodified")
        assert check.passed

    def test_second_run_does_not_overwrite(self, run_result, structured_pdf: Path) -> None:
        result, artifacts = run_result
        second = run_pipeline(structured_pdf, ParserConfig(), artifacts)
        assert second.run_dir != result.run_dir

    def test_table_is_recovered_from_a_real_text_table(self, run_result) -> None:
        """The synthetic table has a genuine text layer, so cells must be recovered.

        This is the control case for the acceptance document, whose tables are
        raster images and correctly recover zero cells.
        """
        result, _ = run_result
        assert result.report.tables, "no table detected in the synthetic fixture"
        assert any(t.num_cells > 0 for t in result.report.tables)

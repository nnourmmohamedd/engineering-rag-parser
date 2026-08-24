"""Integration tests: a real OCR/scanned-profile conversion end to end.

Exercises the genuine OCR path (Phase 5/6/7 of the OCR verification effort)
against a synthetic image-only PDF built at test time, so CI can run it
without the user-supplied OCR benchmark PDF. Skips automatically when
rapidocr_onnxruntime or Docling model weights are unavailable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_rag.pipelines.parsing_pipeline import run_parsing_pipeline
from engineering_rag.services.parser.config import ParserConfig, Profile
from engineering_rag.services.parser.converter import reload_document_json
from engineering_rag.services.parser.models import RunStatus
from engineering_rag.services.parser.preflight import inspect_source
from engineering_rag.services.parser.profiles import choose_profile

from ....conftest import requires_docling_models, requires_rapidocr

pytestmark = [pytest.mark.integration, pytest.mark.slow, requires_docling_models, requires_rapidocr]


@pytest.fixture(scope="module")
def scanned_run_result(synthetic_image_only_ocr_pdf: Path, tmp_path_factory: pytest.TempPathFactory):
    artifacts = tmp_path_factory.mktemp("ocr_artifacts")
    cfg = ParserConfig().with_overrides(profile=Profile.SCANNED)
    return run_parsing_pipeline(synthetic_image_only_ocr_pdf, cfg, artifacts)


class TestImageOnlyDetection:
    def test_preflight_reports_zero_native_characters(
        self, synthetic_image_only_ocr_pdf: Path, config: ParserConfig
    ) -> None:
        manifest = inspect_source(synthetic_image_only_ocr_pdf, config)
        assert manifest.total_char_count == 0
        assert manifest.page_count == 2

    def test_auto_profile_selects_scanned(
        self, synthetic_image_only_ocr_pdf: Path, config: ParserConfig
    ) -> None:
        manifest = inspect_source(synthetic_image_only_ocr_pdf, config)
        decision = choose_profile(manifest, config.with_overrides(profile=Profile.AUTO))
        assert decision.profile is Profile.SCANNED


class TestScannedProfileConversion:
    def test_status_is_not_fail(self, scanned_run_result) -> None:
        assert scanned_run_result.status in (RunStatus.PASS, RunStatus.PASS_WITH_WARNINGS), (
            f"Unexpected FAIL. Failed gates: {[c.check_id for c in scanned_run_result.report.failed_gates]}"
        )

    def test_every_page_represented_in_order(self, scanned_run_result) -> None:
        doc = reload_document_json(scanned_run_result.run_dir / "docling" / "document.json")
        assert len(doc.pages) == 2
        assert sorted(doc.pages.keys()) == [1, 2]

    def test_ocr_engine_recorded_in_manifest(self, scanned_run_result) -> None:
        import json

        manifest = json.loads((scanned_run_result.run_dir / "run_manifest.json").read_text(encoding="utf-8"))
        ocr_options = manifest["docling"]["pipeline_options"]["ocr_options"]
        assert ocr_options is not None
        assert ocr_options["type"] == "RapidOcrOptions"
        assert manifest["docling"]["pipeline_options"]["do_ocr"] is True

    def test_json_reloads_into_docling_model(self, scanned_run_result) -> None:
        doc = reload_document_json(scanned_run_result.run_dir / "docling" / "document.json")
        assert doc is not None

    def test_markdown_is_non_empty(self, scanned_run_result) -> None:
        md = (scanned_run_result.run_dir / "markdown" / "document.md").read_text(encoding="utf-8")
        assert len(md.strip()) > 0

    def test_json_image_uris_are_portable(self, scanned_run_result) -> None:
        """D-3 must hold for OCR runs too: no Windows backslash separators in asset URIs."""
        text = (scanned_run_result.run_dir / "docling" / "document.json").read_text(encoding="utf-8")
        import re

        uris = re.findall(r'"uri"\s*:\s*"([^"]+)"', text)
        assert uris, "expected at least one asset URI in the OCR document JSON"
        assert not any("\\\\" in u for u in uris)

    def test_blank_looking_second_page_is_not_dropped(self, scanned_run_result) -> None:
        """The near-blank source page must still produce a real, provenance-bearing page."""
        doc = reload_document_json(scanned_run_result.run_dir / "docling" / "document.json")
        assert 2 in doc.pages

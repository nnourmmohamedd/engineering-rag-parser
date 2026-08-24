"""Real-document acceptance tests: the already-generated parser outputs for
the engineering PDF and the OCR benchmark PDF, chunked end to end.

Marked ``slow`` and self-skip with an explicit reason when the referenced
parser run directory is absent (a fresh clone has neither the confidential
PDF nor its parser output committed).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_rag.pipelines.chunking_pipeline import run_chunking_pipeline
from engineering_rag.services.chunker import load_config
from engineering_rag.services.chunker.models import ContentType, RunStatus

from ...conftest import requires_chunker_tokenizer

pytestmark = [pytest.mark.slow, pytest.mark.integration, requires_chunker_tokenizer]

ENGINEERING_RUN = Path("data/output/parser/Instrumentation-and-Control-Engineering/20260824T124235Z-01e4d6fa")
OCR_RUN = Path("data/output/parser/scanned_docling_test_image_only/20260824T130311Z-57f84fd5")


def _skip_if_absent(run_dir: Path) -> None:
    if not (run_dir / "docling" / "document.json").is_file():
        pytest.skip(f"Parser run not present at {run_dir}; run the parser first to exercise this test.")


@pytest.fixture(scope="module")
def engineering_pdf_result(tmp_path_factory: pytest.TempPathFactory):
    _skip_if_absent(ENGINEERING_RUN)
    config = load_config("configs/chunker_production.yaml")
    return run_chunking_pipeline(ENGINEERING_RUN, config, tmp_path_factory.mktemp("eng_chunks"))


@pytest.fixture(scope="module")
def ocr_pdf_result(tmp_path_factory: pytest.TempPathFactory):
    _skip_if_absent(OCR_RUN)
    config = load_config("configs/chunker_production.yaml")
    return run_chunking_pipeline(OCR_RUN, config, tmp_path_factory.mktemp("ocr_chunks"))


class TestEngineeringPdfAcceptance:
    def test_status_is_not_fail(self, engineering_pdf_result) -> None:
        assert engineering_pdf_result.status in (RunStatus.PASS.value, RunStatus.PASS_WITH_WARNINGS.value)

    def test_produces_a_substantial_number_of_chunks(self, engineering_pdf_result) -> None:
        assert engineering_pdf_result.chunk_count > 50

    def test_every_content_type_family_represented(self, engineering_pdf_result) -> None:
        types = {c.content_type for c in engineering_pdf_result.chunks}
        assert ContentType.TEXT in types
        assert ContentType.TABLE in types
        assert ContentType.FIGURE in types

    def test_no_chunk_exceeds_max_tokens_unless_flagged(self, engineering_pdf_result) -> None:
        for c in engineering_pdf_result.chunks:
            assert c.token_count <= 256 or c.is_atomic_overflow

    def test_tables_1_and_2_are_represented_with_labels(self, engineering_pdf_result) -> None:
        table_chunks = [c for c in engineering_pdf_result.chunks if c.content_type is ContentType.TABLE]
        labels = {c.table_metadata.detected_label for c in table_chunks if c.table_metadata}
        assert "Table 1" in labels
        assert "Table 2" in labels

    def test_unrecovered_table_warnings_are_propagated(self, engineering_pdf_result) -> None:
        table_chunks = [c for c in engineering_pdf_result.chunks if c.content_type is ContentType.TABLE]
        assert any(c.parser_warnings for c in table_chunks)

    def test_validation_passes_or_only_warns(self, engineering_pdf_result) -> None:
        report_path = engineering_pdf_result.run_dir / "validation_report.json"
        assert report_path.is_file()
        import json

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert not report["checks"] or all(
            c["passed"] or c["severity"] != "CRITICAL" for c in report["checks"]
        )


class TestOcrPdfAcceptance:
    def test_status_is_not_fail(self, ocr_pdf_result) -> None:
        assert ocr_pdf_result.status in (RunStatus.PASS.value, RunStatus.PASS_WITH_WARNINGS.value)

    def test_recovered_table_has_real_cell_content(self, ocr_pdf_result) -> None:
        table_chunks = [c for c in ocr_pdf_result.chunks if c.content_type is ContentType.TABLE]
        assert table_chunks
        assert any(c.table_metadata and c.table_metadata.num_rows > 0 for c in table_chunks)


class TestDeterministicRepeatedRuns:
    def test_engineering_pdf_repeated_run_is_byte_identical(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        _skip_if_absent(ENGINEERING_RUN)
        config = load_config("configs/chunker_production.yaml")
        first = run_chunking_pipeline(ENGINEERING_RUN, config, tmp_path_factory.mktemp("det_a"))
        second = run_chunking_pipeline(ENGINEERING_RUN, config, tmp_path_factory.mktemp("det_b"))
        first_bytes = (first.run_dir / "chunks.jsonl").read_bytes()
        second_bytes = (second.run_dir / "chunks.jsonl").read_bytes()
        assert first_bytes == second_bytes

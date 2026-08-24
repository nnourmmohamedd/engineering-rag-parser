"""Regression tests for the image-only PDF generation utility.

Uses synthetic fixtures built at test time (not the user-supplied OCR
benchmark PDF) so CI can exercise this path without the confidential source
document. Verifies the properties Phase 2 of the OCR verification requires:
zero/negligible extractable text, preserved page count and A4 dimensions,
and a genuine raster image on every page.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ocr"))

from make_image_only_pdf import build_image_only_pdf, page_sizes_pt, render_pages  # noqa: E402


@pytest.fixture(scope="module")
def image_only_output(tmp_path_factory: pytest.TempPathFactory, two_page_native_text_pdf: Path) -> Path:
    dest = tmp_path_factory.mktemp("image_only_out") / "image_only.pdf"
    build_image_only_pdf(two_page_native_text_pdf, dest, dpi=150)
    return dest


class TestRenderPages:
    def test_renders_one_image_per_source_page(self, two_page_native_text_pdf: Path) -> None:
        images = render_pages(two_page_native_text_pdf, dpi=100)
        assert len(images) == 2

    def test_page_sizes_are_a4(self, two_page_native_text_pdf: Path) -> None:
        sizes = page_sizes_pt(two_page_native_text_pdf)
        assert len(sizes) == 2
        for width, height in sizes:
            assert 595 < width < 596
            assert 841 < height < 842


class TestBuildImageOnlyPdf:
    def test_output_file_exists_and_opens(self, image_only_output: Path) -> None:
        from pypdf import PdfReader

        reader = PdfReader(str(image_only_output))
        assert len(reader.pages) == 2

    def test_page_count_preserved(self, image_only_output: Path) -> None:
        from pypdf import PdfReader

        reader = PdfReader(str(image_only_output))
        assert len(reader.pages) == 2

    def test_dimensions_preserved_as_a4(self, image_only_output: Path) -> None:
        from pypdf import PdfReader

        reader = PdfReader(str(image_only_output))
        for page in reader.pages:
            box = page.mediabox
            assert 595 < float(box.width) < 596
            assert 841 < float(box.height) < 842

    def test_no_native_text_layer(self, image_only_output: Path) -> None:
        """The independent extractor must find zero/negligible text -- the core image-only proof."""
        from pdfminer.high_level import extract_text

        text = extract_text(str(image_only_output))
        assert len(text.strip()) == 0

    def test_every_page_has_a_raster_image(self, image_only_output: Path) -> None:
        from pypdf import PdfReader

        reader = PdfReader(str(image_only_output))
        for page in reader.pages:
            assert len(list(page.images)) >= 1

    def test_second_near_blank_page_is_preserved_as_an_image_not_dropped(
        self, image_only_output: Path
    ) -> None:
        """Blank-looking source pages must still become a real page with a raster image."""
        from pypdf import PdfReader

        reader = PdfReader(str(image_only_output))
        assert len(reader.pages) == 2
        assert len(list(reader.pages[1].images)) >= 1

    def test_page_renders_successfully_via_pypdfium2(self, image_only_output: Path) -> None:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(image_only_output))
        try:
            for page in pdf:
                bitmap = page.render(scale=1.0)
                image = bitmap.to_pil()
                assert image.size[0] > 0
                assert image.size[1] > 0
        finally:
            pdf.close()

    def test_deterministic_page_count_and_size_across_runs(
        self, tmp_path: Path, two_page_native_text_pdf: Path
    ) -> None:
        """Re-running the generator on the same source yields the same page geometry."""
        from pypdf import PdfReader

        dest_a = tmp_path / "a.pdf"
        dest_b = tmp_path / "b.pdf"
        build_image_only_pdf(two_page_native_text_pdf, dest_a, dpi=100)
        build_image_only_pdf(two_page_native_text_pdf, dest_b, dpi=100)
        reader_a = PdfReader(str(dest_a))
        reader_b = PdfReader(str(dest_b))
        assert len(reader_a.pages) == len(reader_b.pages)
        for pa, pb in zip(reader_a.pages, reader_b.pages, strict=True):
            assert pa.mediabox.width == pb.mediabox.width
            assert pa.mediabox.height == pb.mediabox.height

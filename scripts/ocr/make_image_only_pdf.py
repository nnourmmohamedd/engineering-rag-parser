"""Render a native-text PDF into a genuine image-only PDF, for OCR benchmarking.

Every source page is rasterised at a configurable DPI (default 300) using
pypdfium2, then rebuilt as a new PDF page containing *only* that raster image
-- no text layer, no hidden OCR text. Page count, page order and page
dimensions (A4) are preserved, including a nearly-blank page, so blank-page
handling is exercised too.

Dependencies are all already present in this project: ``pypdfium2`` (runtime),
``Pillow`` (runtime) and ``reportlab`` (dev, already used to build synthetic
test fixtures). PyMuPDF is deliberately not used (AGPL-3.0, excluded project-wide).

Usage:
    python scripts/ocr/make_image_only_pdf.py \
        --input data/input/ocr/scanned_docling_test_source.pdf \
        --output data/input/ocr/scanned_docling_test_image_only.pdf \
        --dpi 300
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image
from reportlab.pdfgen import canvas as pdfcanvas


def render_pages(source: Path, dpi: int = 300) -> list[Image.Image]:
    """Rasterise every page of ``source`` to a PIL image at ``dpi``, in order."""
    pdf = pdfium.PdfDocument(str(source))
    scale = dpi / 72.0
    images: list[Image.Image] = []
    try:
        for page in pdf:
            bitmap = page.render(scale=scale)
            images.append(bitmap.to_pil().convert("RGB"))
    finally:
        pdf.close()
    return images


def page_sizes_pt(source: Path) -> list[tuple[float, float]]:
    """Page (width, height) in PDF points, in order -- read independently of Docling."""
    pdf = pdfium.PdfDocument(str(source))
    try:
        return [page.get_size() for page in pdf]
    finally:
        pdf.close()


def build_image_only_pdf(source: Path, dest: Path, dpi: int = 300) -> None:
    """Write ``dest`` as an image-only PDF derived from ``source``.

    Deterministic for a fixed (source, dpi) pair: rendering is not
    randomised, and no timestamps or run-specific metadata are embedded
    beyond what reportlab itself always writes into the PDF header.
    """
    sizes = page_sizes_pt(source)
    images = render_pages(source, dpi=dpi)
    if len(images) != len(sizes):
        raise RuntimeError(f"page count mismatch: {len(images)} images vs {len(sizes)} page sizes")

    dest.parent.mkdir(parents=True, exist_ok=True)
    c = pdfcanvas.Canvas(str(dest))
    for image, (width_pt, height_pt) in zip(images, sizes, strict=True):
        c.setPageSize((width_pt, height_pt))
        c.drawInlineImage(image, 0, 0, width=width_pt, height=height_pt)
        c.showPage()
    c.save()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=300)
    args = parser.parse_args()

    build_image_only_pdf(args.input, args.output, dpi=args.dpi)
    print(f"Wrote {args.output} ({args.output.stat().st_size} bytes) at {args.dpi} DPI")


if __name__ == "__main__":
    main()

"""Shared fixtures, including synthetic PDFs built at test time.

Fixtures are generated with ReportLab rather than committed as binaries so the
repository never carries opaque test blobs, and so CI can run the full
integration suite without the confidential acceptance document.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from engineering_rag.services.parser.config import ParserConfig

ACCEPTANCE_PDF = Path("data/input/Instrumentation-and-Control-Engineering.pdf")


@pytest.fixture(scope="session")
def config() -> ParserConfig:
    """Default configuration."""
    return ParserConfig()


@pytest.fixture(scope="session")
def fixtures_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Directory holding generated synthetic PDFs."""
    return tmp_path_factory.mktemp("fixtures")


def _reportlab_available() -> bool:
    try:
        import reportlab  # noqa: F401
    except ImportError:
        return False
    return True


requires_reportlab = pytest.mark.skipif(
    not _reportlab_available(), reason="reportlab is not installed (dev dependency)"
)


@pytest.fixture(scope="session")
def structured_pdf(fixtures_dir: Path) -> Path:
    """A synthetic PDF with headings, nested lists, a table, repeated furniture and an image.

    Deliberately mirrors the shapes the real document exercises: a heading
    hierarchy, an ordered/unordered nested list, a rectangular table, a caption,
    an embedded image, and a header/footer repeated on every page.
    """
    pytest.importorskip("reportlab")
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Image,
        ListFlowable,
        ListItem,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    path = fixtures_dir / "structured.pdf"
    if path.is_file():
        return path

    image_path = _make_png(fixtures_dir / "diagram.png")
    styles = getSampleStyleSheet()

    def furniture(canvas, doc):  # noqa: ANN001 - reportlab callback signature
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawString(20 * mm, 285 * mm, "ACME ENGINEERING — CONFIDENTIAL")
        canvas.drawString(20 * mm, 10 * mm, f"www.example.com    Page {doc.page} of 3")
        canvas.restoreState()

    story = [
        Paragraph("Instrumentation Test Document", styles["Title"]),
        Paragraph("Section 1: Overview", styles["Heading1"]),
        Paragraph(
            "The transmitter FT-101 provides a 4-20 mA signal at 24 V DC. "
            "Accuracy is 0.5% of span at 100 kPa, per ISA-5.1 and the P&ID.",
            styles["BodyText"],
        ),
        Paragraph("1.1 Scope", styles["Heading2"]),
        ListFlowable(
            [
                ListItem(Paragraph("First requirement", styles["BodyText"])),
                ListItem(
                    ListFlowable(
                        [
                            ListItem(Paragraph("Nested item A", styles["BodyText"])),
                            ListItem(Paragraph("Nested item B", styles["BodyText"])),
                        ],
                        bulletType="bullet",
                    )
                ),
                ListItem(Paragraph("Third requirement", styles["BodyText"])),
            ],
            bulletType="1",
        ),
        PageBreak(),
        Paragraph("Section 2: Data", styles["Heading1"]),
        Paragraph("Table 1: Instrument Ranges", styles["BodyText"]),
        Table(
            [
                ["Tag", "Range", "Unit"],
                ["FT-101", "0-100", "kPa"],
                ["PT-202", "0-16", "bar"],
                ["TT-303", "0-250", "degC"],
            ],
            style=TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ]
            ),
        ),
        Spacer(1, 8 * mm),
        PageBreak(),
        Paragraph("Section 3: Figure", styles["Heading1"]),
        Image(str(image_path), width=90 * mm, height=60 * mm),
        Paragraph("Figure 1: Loop diagram", styles["BodyText"]),
    ]

    SimpleDocTemplate(str(path), pagesize=A4).build(story, onFirstPage=furniture, onLaterPages=furniture)
    return path


@pytest.fixture(scope="session")
def image_only_pdf(fixtures_dir: Path) -> Path:
    """A PDF with a single page containing only an image — no text layer at all."""
    pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdfcanvas

    path = fixtures_dir / "image_only.pdf"
    if path.is_file():
        return path
    image_path = _make_png(fixtures_dir / "scan.png", text=False)
    c = pdfcanvas.Canvas(str(path), pagesize=A4)
    c.drawImage(str(image_path), 20 * mm, 100 * mm, width=170 * mm, height=120 * mm)
    c.showPage()
    c.save()
    return path


@pytest.fixture(scope="session")
def two_page_native_text_pdf(fixtures_dir: Path) -> Path:
    """A two-page native-text A4 PDF whose second page is nearly blank.

    Mirrors the shape of the real OCR benchmark source
    (``data/input/ocr/scanned_docling_test_source.pdf``): a content-bearing
    first page and a near-empty second page, so the image-only conversion
    utility and blank-page handling can be regression-tested without the
    confidential/user-supplied fixture.
    """
    pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdfcanvas

    path = fixtures_dir / "two_page_native_text.pdf"
    if path.is_file():
        return path
    c = pdfcanvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, 270 * mm, "SYNTHETIC OCR BENCHMARK")
    c.setFont("Helvetica", 11)
    c.drawString(20 * mm, 250 * mm, "DOC-REF: #TEST-0001")
    c.drawString(20 * mm, 240 * mm, "Tag FT-101 reads 4-20 mA at 24 V DC.")
    c.drawString(20 * mm, 230 * mm, "Status: Active")
    c.drawString(20 * mm, 215 * mm, "Section 1: Overview")
    c.drawString(20 * mm, 205 * mm, "This synthetic benchmark exercises the scanned/OCR conversion path")
    c.drawString(20 * mm, 195 * mm, "end to end: preflight image-only detection, profile selection,")
    c.drawString(20 * mm, 185 * mm, "OCR text recovery, JSON reload and Markdown export.")
    c.drawString(20 * mm, 170 * mm, "Section 2: Instrumentation")
    c.drawString(20 * mm, 160 * mm, "Transmitter PT-202 reads 0-16 bar. Accuracy is 0.5% of span.")
    c.drawString(20 * mm, 150 * mm, "Transmitter TT-303 reads 0-250 degC per ISA-5.1 and the P&ID.")
    c.drawString(20 * mm, 140 * mm, "Section 3: Review")
    c.drawString(20 * mm, 130 * mm, "This page intentionally carries several short, independent lines")
    c.drawString(20 * mm, 120 * mm, "so the rendered raster gives the OCR engine enough signal to")
    c.drawString(20 * mm, 110 * mm, "recover distinct text blocks reliably at 300 DPI.")
    c.showPage()
    # Positioned as a footer (near the bottom, like the real OCR benchmark's
    # near-blank page) rather than mid-page: Docling's OCR layout clustering
    # merges very short, isolated mid-page text blocks with the previous
    # page's content when there is too little else on the page to anchor a
    # page break. A footer-positioned line does not trigger that merge.
    c.setFont("Helvetica", 9)
    c.drawString(
        20 * mm, 12 * mm, "Page 2 of 2 -- intentionally near-blank, generated for OCR benchmark review."
    )
    c.showPage()
    c.save()
    return path


@pytest.fixture(scope="session")
def rotated_pdf(fixtures_dir: Path) -> Path:
    """A two-page PDF whose second page is rotated 90 degrees."""
    pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdfcanvas

    path = fixtures_dir / "rotated.pdf"
    if path.is_file():
        return path
    c = pdfcanvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 12)
    c.drawString(20 * mm, 250 * mm, "Upright page with SIL 2 rating.")
    c.showPage()
    c.setPageRotation(90)
    c.setFont("Helvetica", 12)
    c.drawString(20 * mm, 250 * mm, "Rotated page containing PT-202 at 16 bar.")
    c.showPage()
    c.save()
    return path


def _make_png(path: Path, text: bool = True) -> Path:
    """Draw a small PNG locally with Pillow (no network, no binary fixture)."""
    from PIL import Image, ImageDraw

    if path.is_file():
        return path
    img = Image.new("RGB", (400, 260), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 380, 240], outline="black", width=3)
    draw.line([60, 130, 340, 130], fill="black", width=2)
    draw.ellipse([150, 90, 250, 170], outline="black", width=3)
    if text:
        draw.text((160, 122), "FT-101", fill="black")
    img.save(path, format="PNG")
    return path


@pytest.fixture(scope="session")
def acceptance_pdf() -> Path:
    """The real acceptance document, skipping the test when it is absent.

    Absent by default in a fresh clone: the file is confidential and git-ignored.
    """
    if not ACCEPTANCE_PDF.is_file():
        pytest.skip(
            f"Acceptance PDF not present at {ACCEPTANCE_PDF}. It is intentionally git-ignored; "
            "copy it there to run the full-document acceptance test."
        )
    return ACCEPTANCE_PDF


def docling_models_available() -> bool:
    """Whether Docling model weights look cached, so integration tests can run offline."""
    if os.environ.get("ENGRAG_SKIP_DOCLING") == "1":
        return False
    from pathlib import Path as _P

    for candidate in (
        _P.home() / ".cache" / "huggingface",
        _P.home() / ".cache" / "docling",
        _P(os.environ.get("HF_HOME", "")) if os.environ.get("HF_HOME") else None,
    ):
        if candidate and candidate.exists():
            return True
    return False


requires_docling_models = pytest.mark.skipif(
    not docling_models_available(),
    reason="Docling model weights are not cached; set ENGRAG_SKIP_DOCLING=0 after a first online run.",
)


def _rapidocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


requires_rapidocr = pytest.mark.skipif(
    not _rapidocr_available(),
    reason='rapidocr_onnxruntime is not installed; run `pip install -e ".[ocr]"` to exercise OCR tests.',
)


def _chunker_tokenizer_available() -> bool:
    try:
        from engineering_rag.services.chunker.config import TokenizerOptions
        from engineering_rag.services.chunker.tokenizer import get_tokenizer

        get_tokenizer(TokenizerOptions())
    except Exception:  # noqa: BLE001
        return False
    return True


requires_chunker_tokenizer = pytest.mark.skipif(
    not _chunker_tokenizer_available(),
    reason="The chunker's default tokenizer is not installed/cached/reachable; run "
    '`pip install -e ".[chunking]"` and ensure network access (or a pre-populated HF cache) once.',
)


def _qwen3_tokenizer_available() -> bool:
    try:
        from engineering_rag.services.context_builder.config import TokenizerConfig
        from engineering_rag.services.context_builder.token_counter import get_token_counter

        get_token_counter(TokenizerConfig(backend="qwen3"))
    except Exception:  # noqa: BLE001
        return False
    return True


requires_qwen3_tokenizer = pytest.mark.skipif(
    not _qwen3_tokenizer_available(),
    reason="The Qwen/Qwen3-8B tokenizer is not installed/cached/reachable; run "
    '`pip install -e ".[answering]"` and ensure network access (or a pre-populated HF cache) once.',
)


def _production_model() -> str:
    """The Ollama model tag pinned in the production answering profile, for real answering tests."""
    try:
        from engineering_rag.pipelines.answering_config import load_answering_config

        return load_answering_config(Path("configs/answering_production.yaml")).ollama.model
    except Exception:  # noqa: BLE001
        return "qwen3:8b"


def _ollama_available(model: str | None = None) -> bool:
    """Whether a local Ollama server is reachable and has `model` installed, for real answering tests."""
    if os.environ.get("ENGRAG_SKIP_OLLAMA") == "1":
        return False
    if model is None:
        model = _production_model()
    try:
        from engineering_rag.clients.ollama import OllamaConfig, OllamaHTTPClient

        client = OllamaHTTPClient(
            OllamaConfig(model=model, connect_timeout_seconds=2, read_timeout_seconds=5)
        )
        if not client.health_check():
            return False
        return any(m.name == model for m in client.list_models())
    except Exception:  # noqa: BLE001
        return False


requires_ollama = pytest.mark.skipif(
    not _ollama_available(),
    reason=f"A local Ollama server with {_production_model()!r} installed is not reachable at "
    "http://127.0.0.1:11434; install Ollama, pull the model configured in "
    "configs/answering_production.yaml, and ensure the server is running to exercise these tests.",
)


@pytest.fixture(scope="session")
def synthetic_image_only_ocr_pdf(fixtures_dir: Path, two_page_native_text_pdf: Path) -> Path:
    """A genuine image-only two-page PDF, rasterised from `two_page_native_text_pdf`.

    Used for OCR integration tests that need a *real* image-only document (no
    text layer at all) without depending on the user-supplied OCR benchmark
    PDF, so these tests run in any clone/CI.
    """
    import sys

    path = fixtures_dir / "synthetic_image_only_ocr.pdf"
    if path.is_file():
        return path
    scripts_ocr = Path(__file__).resolve().parents[1] / "scripts" / "ocr"
    sys.path.insert(0, str(scripts_ocr))
    from make_image_only_pdf import build_image_only_pdf

    build_image_only_pdf(two_page_native_text_pdf, path, dpi=300)
    return path

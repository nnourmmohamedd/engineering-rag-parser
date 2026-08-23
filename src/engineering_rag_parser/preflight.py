"""Independent source inventory, built without Docling.

This module is the *control group* of the whole validation design. If the
baseline were produced by Docling, every coverage metric would be Docling
compared against itself and would prove nothing. So the measurements here come
from a separate, permissively licensed stack:

===============  =====================================================
``pypdf``        metadata, PDF version, encryption, outlines,
                 annotations, embedded files, fonts        (BSD-3-Clause)
``pdfminer.six`` per-page text, line geometry, char counts (MIT)
``pypdfium2``    page geometry, raster image objects,
                 page rasterisation for visual review      (BSD-3 / Apache-2.0)
===============  =====================================================

``PyMuPDF``/``fitz`` is deliberately **not** used anywhere in this project: it is
AGPL-3.0 and this parser is intended for corporate engineering use (ADR-003).
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTTextContainer, LTTextLine

from .config import ParserConfig
from .domain import FurnitureCandidate, ImageBlock, SourceManifest, SourcePage
from .normalization import normalize_for_compare, normalize_line, redact, text_sha256

__all__ = ["PreflightError", "inspect_source", "native_page_texts", "render_page_png"]

logger = logging.getLogger(__name__)

_PDF_MAGIC = b"%PDF-"
#: Fraction of page height treated as the header / footer band when looking for
#: repeated furniture. 12% of A4 is ~101 pt, comfortably covering a banner or a
#: "Page N of M" line without reaching into body text.
_BAND_FRACTION = 0.12


class PreflightError(RuntimeError):
    """Raised when the input cannot be safely accepted for parsing."""


class _WarningCollector(logging.Handler):
    """Capture a noisy library's warnings as structured evidence.

    pypdf emits one WARNING per malformed dictionary key. On a document produced
    by a lenient writer that can be hundreds of lines, which buries the preflight
    summary. The anomalies are still real information about source quality, so
    they are collected and summarised into the manifest rather than discarded.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.counts: Counter[str] = Counter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a broken log record must not break preflight
            return
        # Collapse the varying byte offset / key so repeats aggregate into one row.
        key = message.split(" at byte ")[0].strip()
        self.counts[f"{record.name}: {key}"] += 1

    def summary(self) -> list[str]:
        return [f"{msg} (x{n})" for msg, n in sorted(self.counts.items(), key=lambda kv: -kv[1])]


def _sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    """Stream a file through SHA-256 without loading it into memory."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _check_admissible(path: Path, config: ParserConfig) -> None:
    """Enforce the safety limits before any parsing library touches the bytes."""
    if not path.is_file():
        raise PreflightError(f"Input is not a file: {path}")
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > config.limits.max_file_size_mb:
        raise PreflightError(
            f"Input is {size_mb:.1f} MB which exceeds limits.max_file_size_mb "
            f"({config.limits.max_file_size_mb} MB)."
        )
    with path.open("rb") as fh:
        head = fh.read(len(_PDF_MAGIC))
    if head != _PDF_MAGIC:
        raise PreflightError(
            f"Input does not begin with a {_PDF_MAGIC!r} header (found {head!r}); refusing to parse."
        )


def _pdf_version(path: Path) -> str | None:
    """Read the version from the ``%PDF-x.y`` header line."""
    with path.open("rb") as fh:
        line = fh.readline(32)
    text = line.decode("latin-1", errors="replace").strip()
    return text[len(_PDF_MAGIC.decode()) :] if text.startswith("%PDF-") else None


def _collect_pypdf_facts(path: Path, config: ParserConfig) -> dict[str, Any]:
    """Metadata, encryption, outlines, fonts, annotations and attachments.

    Every sub-step is individually guarded: a malformed outline tree or an
    exotic font dictionary must degrade one field, not abort the whole preflight.
    """
    from pypdf import PdfReader

    facts: dict[str, Any] = {
        "is_encrypted": False,
        "metadata": {},
        "outline_entries": [],
        "fonts": [],
        "embedded_files": [],
        "page_count": 0,
        "annotations_per_page": {},
        "links_per_page": {},
    }
    reader = PdfReader(str(path))
    facts["is_encrypted"] = bool(reader.is_encrypted)
    if reader.is_encrypted:
        # An empty user password is common for "protected" but readable PDFs.
        try:
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001 - degrade, do not abort
            logger.warning("Encrypted PDF could not be opened with an empty password: %s", exc)

    facts["page_count"] = len(reader.pages)

    try:
        # Materialise as a plain dict: pypdf returns DocumentInformation | None,
        # and the `or {}` fallback leaves the element types unresolvable.
        meta: dict[Any, Any] = dict(reader.metadata or {})
        facts["metadata"] = {
            str(k).lstrip("/"): redact(str(v), 300, config.redact_text_samples)
            for k, v in meta.items()
            if v is not None
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read document metadata: %s", exc)

    try:
        facts["outline_entries"] = _flatten_outline(reader)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read outline/bookmarks: %s", exc)

    try:
        names = reader.attachments or {}
        facts["embedded_files"] = sorted(str(k) for k in names)
    except Exception as exc:  # noqa: BLE001
        logger.debug("No embedded attachments readable: %s", exc)

    fonts: set[str] = set()
    for idx, page in enumerate(reader.pages, start=1):
        try:
            res = page.get("/Resources") or {}
            font_dict = res.get("/Font") if hasattr(res, "get") else None
            if font_dict:
                for ref in font_dict.values():
                    obj = ref.get_object() if hasattr(ref, "get_object") else ref
                    base = obj.get("/BaseFont") if hasattr(obj, "get") else None
                    if base:
                        fonts.add(str(base).lstrip("/"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Font inspection failed on page %d: %s", idx, exc)
        try:
            annots = page.get("/Annots") or []
            annot_list = list(annots)
            facts["annotations_per_page"][idx] = len(annot_list)
            links = 0
            for a in annot_list:
                obj = a.get_object() if hasattr(a, "get_object") else a
                if hasattr(obj, "get") and str(obj.get("/Subtype", "")) == "/Link":
                    links += 1
            facts["links_per_page"][idx] = links
        except Exception as exc:  # noqa: BLE001
            logger.debug("Annotation inspection failed on page %d: %s", idx, exc)
    facts["fonts"] = sorted(fonts)
    return facts


def _flatten_outline(reader: Any, limit: int = 500) -> list[dict[str, Any]]:
    """Flatten the bookmark tree into ``{title, level, page}`` records."""
    out: list[dict[str, Any]] = []

    def walk(nodes: Any, level: int) -> None:
        for node in nodes:
            if len(out) >= limit:
                return
            if isinstance(node, list):
                walk(node, level + 1)
                continue
            title = str(getattr(node, "title", "") or "")
            page_no: int | None = None
            try:
                page_no = reader.get_destination_page_number(node) + 1
            except Exception:  # noqa: BLE001 - destination may be unresolvable
                page_no = None
            out.append({"title": title, "level": level, "page": page_no})

    try:
        walk(reader.outline, 1)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Outline traversal stopped early: %s", exc)
    return out


def _page_text_lines(path: Path, config: ParserConfig) -> dict[int, list[tuple[str, float, float]]]:
    """Per-page text lines with vertical position, via pdfminer.six.

    Returns ``{page_no: [(text, y_bottom, y_top), ...]}`` in PDF coordinates
    (origin bottom-left). Vertical position is what lets furniture detection
    require *both* repeated text and a stable band, instead of deleting any
    sentence that happens to occur twice.
    """
    laparams = LAParams(line_margin=0.5, char_margin=2.0, word_margin=0.1, detect_vertical=False)
    result: dict[int, list[tuple[str, float, float]]] = {}
    max_pages = config.limits.max_pages
    for idx, layout in enumerate(extract_pages(str(path), laparams=laparams, maxpages=max_pages), start=1):
        lines: list[tuple[str, float, float]] = []
        for element in layout:
            if not isinstance(element, LTTextContainer):
                continue
            for line in element:
                if not isinstance(line, LTTextLine):
                    continue
                text = line.get_text().strip()
                if text:
                    lines.append((text, float(line.y0), float(line.y1)))
        result[idx] = lines
    return result


def _classify_furniture_kind(normalized: str, band: str) -> str:
    """Label a repeated line by what it appears to be.

    Purely textual heuristics on the *normalised* form (digits already masked to
    ``#``), so ``page # of #`` matches every page-number variant at once.
    """
    if "page #" in normalized or normalized.strip() in {"#", "# of #"}:
        return "page_number"
    if "www." in normalized or "http" in normalized or ".com" in normalized:
        return "website"
    if band == "header":
        return "header"
    if band == "footer":
        return "footer"
    return "other"


def _detect_text_furniture(
    lines_by_page: dict[int, list[tuple[str, float, float]]],
    page_heights: dict[int, float],
    min_fraction: float,
) -> list[FurnitureCandidate]:
    """Find lines that repeat across pages *and* stay in a header/footer band."""
    total_pages = len(lines_by_page) or 1
    # key -> band -> {pages}, plus one representative raw text per key.
    occurrences: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    examples: dict[str, str] = {}

    for page_no, lines in lines_by_page.items():
        height = page_heights.get(page_no, 842.0)
        band_h = height * _BAND_FRACTION
        for text, y0, y1 in lines:
            key = normalize_line(text)
            if not key or len(key) < 2:
                continue
            if y0 >= height - band_h:
                band = "header"
            elif y1 <= band_h:
                band = "footer"
            else:
                band = "body"
            occurrences[key][band].add(page_no)
            examples.setdefault(key, text)

    candidates: list[FurnitureCandidate] = []
    for key, bands in occurrences.items():
        for band, pages in bands.items():
            if band == "body":
                continue
            fraction = len(pages) / total_pages
            if fraction < min_fraction:
                continue
            candidates.append(
                FurnitureCandidate(
                    text=examples[key],
                    normalized=key,
                    pages=sorted(pages),
                    page_fraction=round(fraction, 4),
                    band=band,  # type: ignore[arg-type]
                    kind=_classify_furniture_kind(key, band),  # type: ignore[arg-type]
                )
            )
    candidates.sort(key=lambda c: (-c.page_fraction, c.normalized))
    return candidates


def inspect_source(path: Path | str, config: ParserConfig) -> SourceManifest:
    """Build the independent source manifest for ``path``.

    Raises:
        PreflightError: if the file fails the safety limits, is not a PDF, or
            exceeds the configured page ceiling.
    """
    pdf_path = Path(path)
    _check_admissible(pdf_path, config)

    sha = _sha256_file(pdf_path)
    size = pdf_path.stat().st_size
    logger.info("Preflight: %s (%d bytes, sha256=%s…)", pdf_path.name, size, sha[:12])

    collector = _WarningCollector()
    pypdf_logger = logging.getLogger("pypdf")
    pypdf_logger.addHandler(collector)
    previous_propagate = pypdf_logger.propagate
    pypdf_logger.propagate = False
    try:
        facts = _collect_pypdf_facts(pdf_path, config)
    finally:
        pypdf_logger.removeHandler(collector)
        pypdf_logger.propagate = previous_propagate
    anomalies = collector.summary()
    if anomalies:
        logger.info("Source structural anomalies recorded: %d distinct kind(s)", len(anomalies))

    if facts["page_count"] > config.limits.max_pages:
        raise PreflightError(
            f"Document has {facts['page_count']} pages, exceeding limits.max_pages ({config.limits.max_pages})."
        )

    lines_by_page = _page_text_lines(pdf_path, config)

    pages: list[SourcePage] = []
    page_heights: dict[int, float] = {}
    # Signature -> pages, used to separate decorative repeated images from real diagrams.
    image_signatures: Counter[tuple[int, int, int, int, int, int]] = Counter()
    page_image_rows: dict[int, list[tuple[tuple[int, int, int, int, int, int], ImageBlock]]] = {}

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        for i in range(len(doc)):
            page_no = i + 1
            page = doc[i]
            width, height = (float(v) for v in page.get_size())
            page_heights[page_no] = height
            area = width * height or 1.0

            rows: list[tuple[tuple[int, int, int, int, int, int], ImageBlock]] = []
            try:
                for obj in page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE], max_depth=15):
                    bounds = obj.get_bounds()
                    try:
                        px_w, px_h = obj.get_px_size()
                    except Exception:  # noqa: BLE001
                        px_w = px_h = 0
                    bbox = (float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))
                    frac = abs((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) / area
                    sig = (
                        round(bbox[0]),
                        round(bbox[1]),
                        round(bbox[2]),
                        round(bbox[3]),
                        int(px_w),
                        int(px_h),
                    )
                    image_signatures[sig] += 1
                    rows.append(
                        (
                            sig,
                            ImageBlock(
                                width_px=int(px_w) or None,
                                height_px=int(px_h) or None,
                                bbox=bbox,
                                area_fraction=round(frac, 5),
                            ),
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Image object inspection failed on page %d: %s", page_no, exc)
            page_image_rows[page_no] = rows

            lines = lines_by_page.get(page_no, [])
            page_text = "\n".join(t for t, _, _ in lines)
            normalized = normalize_for_compare(page_text)
            band_h = height * _BAND_FRACTION

            pages.append(
                SourcePage(
                    page_no=page_no,
                    width_pt=round(width, 2),
                    height_pt=round(height, 2),
                    rotation=int(page.get_rotation()),
                    char_count=len(page_text),
                    word_count=len(normalized.split()),
                    line_count=len(lines),
                    text_sha256=text_sha256(page_text),
                    text_sample=redact(page_text, config.text_sample_chars, config.redact_text_samples),
                    image_count=len(rows),
                    images=[blk for _, blk in rows],
                    image_area_fraction=round(sum(b.area_fraction or 0.0 for _, b in rows), 5),
                    annotation_count=int(facts["annotations_per_page"].get(page_no, 0)),
                    link_count=int(facts["links_per_page"].get(page_no, 0)),
                    header_candidates=[t for t, y0, _ in lines if y0 >= height - band_h][:5],
                    footer_candidates=[t for t, _, y1 in lines if y1 <= band_h][:5],
                )
            )
    finally:
        doc.close()

    total_pages = len(pages) or 1
    repeat_cutoff = max(2, int(total_pages * config.export.furniture_min_page_fraction))

    # Second pass: now that every signature count is known, flag each page using
    # only its *substantive* (non-repeated) imagery. Counting the watermark and
    # banner here would mark all 27 pages "image-heavy" and destroy the signal.
    for page in pages:
        rows = page_image_rows[page.page_no]
        for sig, blk in rows:
            blk.is_repeated = image_signatures[sig] >= repeat_cutoff
        substantive = [blk for sig, blk in rows if image_signatures[sig] < repeat_cutoff]
        substantive_area = sum(b.area_fraction or 0.0 for b in substantive)
        page.substantive_image_count = len(substantive)
        page.substantive_image_area_fraction = round(substantive_area, 5)
        page.is_empty = page.char_count == 0
        page.is_sparse_text = page.char_count < config.thresholds.sparse_text_char_threshold
        page.is_image_heavy = substantive_area >= config.thresholds.image_heavy_area_fraction
        # Review is driven by PRESENCE, not area. An area threshold alone would
        # let a small-but-real figure (a hook-up detail, a wiring stub) pass
        # unreviewed simply for being modest in size — exactly the silent loss
        # this parser is supposed to make impossible.
        page.needs_visual_review = bool(substantive) or page.is_sparse_text or page.is_empty

    furniture = _detect_text_furniture(lines_by_page, page_heights, config.export.furniture_min_page_fraction)
    for sig, count in image_signatures.items():
        if count >= repeat_cutoff:
            furniture.append(
                FurnitureCandidate(
                    text=f"[image {sig[4]}x{sig[5]}px at bbox {sig[:4]}]",
                    normalized=f"image:{sig}",
                    pages=sorted(
                        p for p in range(1, total_pages + 1) if any(s == sig for s, _ in page_image_rows[p])
                    ),
                    page_fraction=round(count / total_pages, 4),
                    band="header" if sig[1] > 600 else "body",
                    kind="watermark" if sig[4] == sig[5] else "other",
                )
            )

    manifest = SourceManifest(
        filename=pdf_path.name,
        byte_size=size,
        sha256=sha,
        mime_guess="application/pdf",
        magic_ok=True,
        pdf_version=_pdf_version(pdf_path),
        is_encrypted=bool(facts["is_encrypted"]),
        page_count=len(pages),
        metadata=facts["metadata"],
        outline_entries=facts["outline_entries"],
        fonts=facts["fonts"],
        embedded_files=facts["embedded_files"],
        total_char_count=sum(p.char_count for p in pages),
        total_word_count=sum(p.word_count for p in pages),
        total_image_count=sum(p.image_count for p in pages),
        pages=pages,
        furniture_candidates=furniture,
        sparse_pages=[p.page_no for p in pages if p.is_sparse_text],
        image_heavy_pages=[p.page_no for p in pages if p.is_image_heavy],
        empty_pages=[p.page_no for p in pages if p.is_empty],
        pages_with_substantive_images=[p.page_no for p in pages if p.substantive_image_count],
        visual_review_pages=[p.page_no for p in pages if p.needs_visual_review],
        substantive_image_count=sum(p.substantive_image_count for p in pages),
        decorative_image_count=sum(p.image_count - p.substantive_image_count for p in pages),
        source_anomalies=anomalies,
        tools=_tool_versions(),
        generated_at_utc=datetime.now(timezone.utc),
    )
    logger.info(
        "Preflight complete: %d pages, %d chars, %d images (%d sparse, %d image-heavy)",
        manifest.page_count,
        manifest.total_char_count,
        manifest.total_image_count,
        len(manifest.sparse_pages),
        len(manifest.image_heavy_pages),
    )
    return manifest


def _tool_versions() -> dict[str, str]:
    """Record which library versions produced this manifest, for reproducibility."""
    import pdfminer
    import pypdf
    from pypdfium2.version import PDFIUM_INFO, PYPDFIUM_INFO

    return {
        "pypdf": str(pypdf.__version__),
        "pdfminer.six": str(pdfminer.__version__),
        "pypdfium2": str(PYPDFIUM_INFO),
        "pdfium": str(PDFIUM_INFO),
    }


def native_page_texts(pdf_path: Path | str, config: ParserConfig) -> dict[int, str]:
    """Native per-page text, for in-memory validation only.

    This is the independent baseline the coverage checks compare Docling
    against. It is deliberately **not** stored in ``source/manifest.json``: the
    document may be confidential, and writing its full text into a JSON artifact
    would create an easier-to-leak copy than the PDF itself. Callers hold it in
    memory for the duration of a run and discard it.
    """
    lines_by_page = _page_text_lines(Path(pdf_path), config)
    return {page_no: "\n".join(t for t, _, _ in lines) for page_no, lines in lines_by_page.items()}


def render_page_png(pdf_path: Path, page_no: int, dest: Path, scale: float = 1.5) -> Path:
    """Rasterise one page to PNG for the visual review artifacts.

    Uses PDFium locally; nothing is uploaded. ``page_no`` is 1-based.

    Raises:
        PreflightError: if ``page_no`` is outside the document.
    """
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        if not 1 <= page_no <= len(doc):
            raise PreflightError(f"Page {page_no} out of range (document has {len(doc)} pages).")
        bitmap = doc[page_no - 1].render(scale=scale)
        image = bitmap.to_pil()
        dest.parent.mkdir(parents=True, exist_ok=True)
        image.save(dest, format="PNG", optimize=True)
        return dest
    finally:
        doc.close()

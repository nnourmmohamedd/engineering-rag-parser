"""Build an independent, machine-readable OCR ground-truth manifest.

Inspects a native-text PDF using only the project's existing independent PDF
toolchain (pypdf, pdfminer.six, pypdfium2, Pillow) -- never Docling -- so the
ground truth used to evaluate Docling's OCR output is not produced by the tool
under test.

Usage:
    python scripts/ocr/build_ground_truth.py \
        --input data/input/ocr/scanned_docling_test_source.pdf \
        --output data/output/ocr_validation/ground_truth_manifest.json \
        --critical-tokens scripts/ocr/critical_tokens.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer
from pypdf import PdfReader


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _page_texts(path: Path) -> list[str]:
    texts: list[str] = []
    for page_layout in extract_pages(str(path)):
        chunks = [element.get_text() for element in page_layout if isinstance(element, LTTextContainer)]
        texts.append("".join(chunks))
    return texts


def _image_count_per_page(reader: PdfReader) -> list[int]:
    counts = []
    for page in reader.pages:
        counts.append(len(list(page.images)))
    return counts


def build_manifest(input_path: Path, critical_tokens: list[str] | None = None) -> dict[str, Any]:
    reader = PdfReader(str(input_path))
    page_texts = _page_texts(input_path)
    image_counts = _image_count_per_page(reader)

    pages: list[dict[str, Any]] = []
    for i, page in enumerate(reader.pages):
        text = page_texts[i] if i < len(page_texts) else ""
        box = page.mediabox
        words = text.split()
        pages.append(
            {
                "index": i,
                "page_number": i + 1,
                "width_pt": float(box.width),
                "height_pt": float(box.height),
                "rotation_deg": int(page.get("/Rotate") or 0),
                "char_count": len(text),
                "word_count": len(words),
                "image_count": image_counts[i] if i < len(image_counts) else 0,
                "is_nearly_blank": len(text.strip()) < 200,
                "text": text,
            }
        )

    total_chars = sum(p["char_count"] for p in pages)
    total_words = sum(p["word_count"] for p in pages)
    full_text = "\n".join(p["text"] for p in pages)

    found_tokens = {}
    if critical_tokens:
        for token in critical_tokens:
            found_tokens[token] = token in full_text

    return {
        "source_path": str(input_path.as_posix()),
        "sha256": _sha256(input_path),
        "size_bytes": input_path.stat().st_size,
        "page_count": len(reader.pages),
        "producer": (reader.metadata or {}).get("/Producer") if reader.metadata else None,
        "metadata": {k: str(v) for k, v in (reader.metadata or {}).items()} if reader.metadata else {},
        "total_char_count": total_chars,
        "total_word_count": total_words,
        "pages": pages,
        "critical_tokens": critical_tokens or [],
        "critical_tokens_present_in_source": found_tokens,
        "tooling": {
            "extractor": "pdfminer.six + pypdf (independent of Docling)",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--critical-tokens", type=Path, default=None)
    args = parser.parse_args()

    critical_tokens: list[str] | None = None
    if args.critical_tokens and args.critical_tokens.is_file():
        critical_tokens = json.loads(args.critical_tokens.read_text(encoding="utf-8"))

    manifest = build_manifest(args.input, critical_tokens)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {args.output} ({args.output.stat().st_size} bytes)")
    print(
        f"Pages: {manifest['page_count']}, chars: {manifest['total_char_count']}, words: {manifest['total_word_count']}"
    )


if __name__ == "__main__":
    main()

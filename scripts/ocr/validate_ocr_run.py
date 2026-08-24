"""Compare an OCR/scanned run's output against the independent ground-truth manifest.

Loads `docling/document.json` (reloaded through the current DoclingDocument
model) and `markdown/document.md` from a completed run directory, and compares
them against the ground-truth manifest built by `build_ground_truth.py` from
the native-text source PDF using normalized character/word/critical-token
recall -- the same normalization functions the rest of this project's
validation framework uses, so the comparison methodology is not bespoke to
OCR.

Usage:
    python scripts/ocr/validate_ocr_run.py \
        --run artifacts/scanned_docling_test_image_only/<run-id> \
        --ground-truth artifacts/ocr_validation/ground_truth_manifest.json \
        --output artifacts/ocr_validation/<run-id>_ocr_validation.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from engineering_rag_parser.normalization import (
    critical_tokens as extract_critical_tokens,
)
from engineering_rag_parser.normalization import (
    normalize_for_compare,
    token_recall,
    word_tokens,
)
from engineering_rag_parser.parser import reload_document_json


def _load_ground_truth(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_run(run_dir: Path, ground_truth: dict[str, Any]) -> dict[str, Any]:
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    md_path = run_dir / "markdown" / "document.md"
    json_path = run_dir / "docling" / "document.json"
    markdown_text = md_path.read_text(encoding="utf-8") if md_path.is_file() else ""

    gt_text = "\n".join(p["text"] for p in ground_truth["pages"])
    gt_norm = normalize_for_compare(gt_text)
    md_norm = normalize_for_compare(markdown_text)

    gt_words = set(word_tokens(gt_norm))
    md_words = set(word_tokens(md_norm))

    gt_critical = extract_critical_tokens(gt_text)
    md_critical = extract_critical_tokens(markdown_text)

    critical_token_hits = {
        token: (token in markdown_text) for token in ground_truth.get("critical_tokens", [])
    }
    critical_token_recall = (
        sum(critical_token_hits.values()) / len(critical_token_hits) if critical_token_hits else 1.0
    )

    json_reload_ok = False
    reload_error: str | None = None
    doc = None
    if json_path.is_file():
        try:
            doc = reload_document_json(json_path)
            json_reload_ok = True
        except Exception as exc:  # noqa: BLE001 - record, do not hide
            reload_error = f"{type(exc).__name__}: {exc}"

    page_count_source = ground_truth["page_count"]
    page_count_parsed = len(doc.pages) if doc is not None else None

    pipeline_options = manifest.get("docling", {}).get("pipeline_options", {})
    ocr_options = pipeline_options.get("ocr_options") or {}
    confidence = manifest.get("docling", {}).get("conversion", {}).get("confidence", {})

    result: dict[str, Any] = {
        "run_dir": str(run_dir.as_posix()),
        "profile": manifest.get("profile"),
        "ocr_engine": ocr_options.get("type"),
        "ocr_backend": ocr_options.get("backend"),
        "ocr_mode": ocr_options.get("mode"),
        "ocr_languages": ocr_options.get("lang"),
        "ocr_score": confidence.get("ocr_score"),
        "do_ocr": pipeline_options.get("do_ocr"),
        "status": manifest.get("status"),
        "conversion_runtime_s": manifest.get("timings_s", {}).get("conversion_s"),
        "page_count_source": page_count_source,
        "page_count_parsed": page_count_parsed,
        "page_count_match": page_count_parsed == page_count_source,
        "markdown_non_empty": len(markdown_text.strip()) > 0,
        "markdown_bytes": len(markdown_text.encode("utf-8")),
        "json_reloads_into_model": json_reload_ok,
        "json_reload_error": reload_error,
        "char_recall_normalized": (round(len(md_norm) / len(gt_norm), 4) if gt_norm else None),
        "word_type_recall": round(token_recall(gt_words, md_words), 4) if gt_words else None,
        "critical_token_recall": round(critical_token_recall, 4),
        "critical_tokens_missing": [t for t, hit in critical_token_hits.items() if not hit],
        "critical_tokens_total": len(critical_token_hits),
        "critical_tokens_recovered": sum(critical_token_hits.values()),
        "gt_word_type_count": len(gt_words),
        "md_word_type_count": len(md_words),
        "gt_critical_token_count": len(gt_critical),
        "md_critical_token_count": len(md_critical),
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    ground_truth = _load_ground_truth(args.ground_truth)
    result = validate_run(args.run, ground_truth)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

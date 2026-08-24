"""Reproducible comparison: this project's hierarchical+recursive chunker vs.
Docling's own ``HybridChunker``, on the same document and the same tokenizer.

The production strategy remains hierarchical-first, conditional recursive
refinement (see ``docs/chunker/MENTOR_EXPLANATION.md``) — this script exists
to produce honest, reproducible evidence for that choice, not to replace it.

Usage:
    python scripts/chunker/compare_hybrid_baseline.py \
        --input data/output/parser/<document>/<run-id> \
        --output docs/chunker/_generated/<document>_baseline_comparison.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from docling_core.transforms.chunker import HybridChunker
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer

from engineering_rag.services.chunker.config import ChunkerConfig, load_config
from engineering_rag.services.chunker.loader import load_document
from engineering_rag.services.chunker.service import ChunkerRequest, ChunkerService


def _stats(token_counts: list[int]) -> dict[str, float]:
    if not token_counts:
        return {"min": 0, "median": 0, "mean": 0, "p95": 0, "max": 0}
    ordered = sorted(token_counts)
    n = len(ordered)
    p95_idx = min(n - 1, int(round(0.95 * (n - 1))))
    return {
        "min": ordered[0],
        "median": statistics.median(ordered),
        "mean": round(statistics.fmean(ordered), 2),
        "p95": ordered[p95_idx],
        "max": ordered[-1],
    }


def _run_production(input_path: Path, config: ChunkerConfig, output_root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    result = ChunkerService().run(
        ChunkerRequest(input_path=input_path, config=config, output_root=output_root)
    )
    elapsed = time.perf_counter() - started

    token_counts = [c.token_count for c in result.chunks]
    empty = sum(1 for c in result.chunks if not c.text.strip())
    oversized = sum(
        1 for c in result.chunks if c.token_count > config.max_tokens and not c.is_atomic_overflow
    )
    content_types: dict[str, int] = {}
    for c in result.chunks:
        content_types[c.content_type.value] = content_types.get(c.content_type.value, 0) + 1
    represented_refs = {ref for c in result.chunks for ref in c.source_element_refs}
    heading_paths_present = sum(1 for c in result.chunks if c.heading_path)
    duplicate_texts = len(token_counts) - len({c.text for c in result.chunks})

    return {
        "approach": "hierarchical_plus_conditional_recursive (production)",
        "total_chunks": len(result.chunks),
        "content_type_distribution": content_types,
        "token_stats": _stats(token_counts),
        "empty_chunks": empty,
        "oversized_chunks_unflagged": oversized,
        "source_elements_represented": len(represented_refs),
        "heading_path_preserved_fraction": round(heading_paths_present / len(result.chunks), 4)
        if result.chunks
        else 0,
        "duplicate_content_chunks": duplicate_texts,
        "processing_time_s": round(elapsed, 4),
        "run_dir": str(result.run_dir),
    }


def _run_hybrid(doc: Any, config: ChunkerConfig) -> dict[str, Any]:
    tokenizer = HuggingFaceTokenizer.from_pretrained(
        model_name=config.tokenizer.name, max_tokens=config.max_tokens
    )
    chunker = HybridChunker(
        tokenizer=tokenizer,
        repeat_table_header=config.repeat_table_headers,
        merge_peers=config.merge_small_chunks,
    )

    started = time.perf_counter()
    chunks = list(chunker.chunk(doc))
    elapsed = time.perf_counter() - started

    token_counts = [tokenizer.count_tokens(text=chunker.contextualize(chunk=c)) for c in chunks]
    empty = sum(1 for c in chunks if not c.text.strip())
    oversized = sum(1 for tc in token_counts if tc > config.max_tokens)
    represented_refs = {item.self_ref for c in chunks for item in c.meta.doc_items}
    heading_paths_present = sum(1 for c in chunks if c.meta.headings)
    duplicate_texts = len(chunks) - len({c.text for c in chunks})

    return {
        "approach": "docling_hybrid_chunker (baseline)",
        "total_chunks": len(chunks),
        "content_type_distribution": {
            "undifferentiated": len(chunks)
        },  # HybridChunker does not classify content type
        "token_stats": _stats(token_counts),
        "empty_chunks": empty,
        "oversized_chunks_unflagged": oversized,
        "source_elements_represented": len(represented_refs),
        "heading_path_preserved_fraction": round(heading_paths_present / len(chunks), 4) if chunks else 0,
        "duplicate_content_chunks": duplicate_texts,
        "processing_time_s": round(elapsed, 4),
    }


def compare(input_path: Path, config_path: Path, output_root: Path) -> dict[str, Any]:
    config = ChunkerConfig() if config_path is None else load_config(config_path)
    doc, identity = load_document(input_path)

    production = _run_production(input_path, config, output_root)
    hybrid = _run_hybrid(doc, config)

    # Determinism check: run the production pipeline twice, byte-compare.
    second = ChunkerService().run(
        ChunkerRequest(input_path=input_path, config=config, output_root=output_root)
    )
    first_chunks_path = Path(production["run_dir"]) / "chunks.jsonl"
    second_chunks_path = second.run_dir / "chunks.jsonl"
    deterministic = first_chunks_path.read_bytes() == second_chunks_path.read_bytes()

    return {
        "source": {"filename": identity.source_filename, "sha256": identity.source_sha256},
        "tokenizer": config.tokenizer.name,
        "max_tokens": config.max_tokens,
        "production": production,
        "hybrid_baseline": hybrid,
        "production_deterministic_repeat_run": deterministic,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/chunker_production.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("data/output/chunker"))
    args = parser.parse_args()

    result = compare(args.input, args.config, args.output_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""The chunker service's public interface: ``ChunkerService``, ``ChunkerRequest``, ``ChunkerResult``.

Owns the exact pipeline sequence: load & validate document.json → hierarchical
chunking → figure recovery → tokenizer-based measurement → conditional
type-aware refinement (recursive text / table rows / list items / code
blocks / atomic equations) → safe small-sibling merging → stable IDs and
navigation links → validation → ``chunks.jsonl`` + ``manifest.json`` +
``validation_report.json`` + ``chunking_summary.md``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engineering_rag.utils.hashing import sha256_file
from engineering_rag.utils.logging import (
    RunContextFilter,
    attach_run_file_handler,
    bind_run_context,
    current_context,
    detach_handler,
)

from . import CHUNKER_VERSION
from .artifacts import ChunkerRunDirectory
from .config import ChunkerConfig
from .finalize import finalize_chunks
from .hierarchical import build_hierarchical_chunks
from .ids import document_id as compute_document_id
from .internal import WorkingChunk
from .linking import provisional_ids
from .loader import load_document
from .merging import merge_small_chunks
from .models import Chunk, ChunkManifest, ContentType
from .recursive import split_oversized_text_chunk
from .refs import build_ref_index
from .summary import render_summary_markdown
from .tokenizer import get_tokenizer
from .type_handlers.code import refine_code_chunk
from .type_handlers.equations import refine_equation_chunk
from .type_handlers.figures import build_figure_chunks
from .type_handlers.lists import refine_list_chunk
from .type_handlers.tables import build_uncovered_table_chunks, refine_table_chunk
from .validation import validate_chunks

__all__ = ["ChunkerRequest", "ChunkerResult", "ChunkerService"]

logger = logging.getLogger(__name__)


@dataclass
class ChunkerRequest:
    """Everything the chunker service needs to run once."""

    input_path: Path
    config: ChunkerConfig
    output_root: Path | None = None

    def __post_init__(self) -> None:
        self.input_path = Path(self.input_path)
        self.output_root = Path(self.output_root) if self.output_root is not None else self.config.output_root


@dataclass
class ChunkerResult:
    """Everything a caller needs after a run."""

    run_dir: Path
    status: str
    chunk_count: int
    manifest: ChunkManifest
    chunks: list[Chunk] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return 1 if self.status == "FAIL" else 0


def _page_sort_key(chunk: WorkingChunk, fallback_index: int) -> tuple[int, int]:
    page = min(chunk.page_numbers) if chunk.page_numbers else 10**9
    return (page, fallback_index)


def _refine(
    chunk: WorkingChunk,
    *,
    ref_index: dict[str, Any],
    config: ChunkerConfig,
    tokenizer: Any,
    validation_report: dict[str, Any],
) -> list[WorkingChunk]:
    if chunk.content_type is ContentType.TEXT:
        return split_oversized_text_chunk(chunk, config=config, tokenizer=tokenizer)
    if chunk.content_type is ContentType.TABLE:
        return refine_table_chunk(
            chunk,
            ref_index=ref_index,
            config=config,
            tokenizer=tokenizer,
            validation_report=validation_report,
        )
    if chunk.content_type is ContentType.LIST:
        return refine_list_chunk(chunk, config=config, tokenizer=tokenizer)
    if chunk.content_type is ContentType.CODE:
        return refine_code_chunk(chunk, config=config, tokenizer=tokenizer)
    if chunk.content_type is ContentType.EQUATION:
        return refine_equation_chunk(chunk, config=config, tokenizer=tokenizer)
    # FIGURE chunks are already atomic and measured by build_figure_chunks.
    return [chunk]


class ChunkerService:
    """Owns the complete chunker-domain workflow for one document.json."""

    def run(self, request: ChunkerRequest) -> ChunkerResult:
        config = request.config
        timings: dict[str, float] = {}

        context = current_context()
        bind_run_context(context, stage="load")

        started = time.perf_counter()
        doc, identity = load_document(request.input_path)
        timings["load_s"] = time.perf_counter() - started

        document_id = compute_document_id(identity.source_sha256)
        bind_run_context(context, document_id=identity.source_filename, stage="hierarchical_chunking")

        run = ChunkerRunDirectory.create(
            Path(request.output_root or config.output_root),
            Path(identity.source_filename).stem,
            identity.source_sha256,
        )
        bind_run_context(context, run_id=run.root.name)
        file_handler = attach_run_file_handler(run.path_for("logs/chunker.log"))
        try:
            return self._run_after_directory_created(
                doc=doc,
                identity=identity,
                document_id=document_id,
                config=config,
                run=run,
                timings=timings,
                context=context,
            )
        finally:
            detach_handler(file_handler)

    def _run_after_directory_created(
        self,
        *,
        doc: Any,
        identity: Any,
        document_id: str,
        config: ChunkerConfig,
        run: ChunkerRunDirectory,
        timings: dict[str, float],
        context: RunContextFilter,
    ) -> ChunkerResult:
        tokenizer = get_tokenizer(config.tokenizer)
        ref_index = build_ref_index(doc)

        # --- 1. Hierarchical chunking + figure recovery -----------------------
        started = time.perf_counter()
        hier_chunks = build_hierarchical_chunks(doc)
        covered_table_refs = {
            ref for c in hier_chunks if c.content_type is ContentType.TABLE for ref in c.source_element_refs
        }
        recovered_table_chunks = build_uncovered_table_chunks(
            doc,
            covered_refs=covered_table_refs,
            config=config,
            tokenizer=tokenizer,
            validation_report=identity.validation_report,
        )
        figure_chunks = build_figure_chunks(
            doc, config=config, tokenizer=tokenizer, validation_report=identity.validation_report
        )
        combined_with_index = list(enumerate(hier_chunks + recovered_table_chunks + figure_chunks))
        combined_with_index.sort(key=lambda pair: _page_sort_key(pair[1], pair[0]))
        combined = [chunk for _, chunk in combined_with_index]
        timings["hierarchical_chunking_s"] = time.perf_counter() - started

        # --- 2. Tokenizer-based measurement + conditional type-aware refinement
        bind_run_context(context, stage="refinement")
        started = time.perf_counter()
        pre_refine_ids = provisional_ids(combined, document_id=document_id)
        refined: list[WorkingChunk] = []
        recursively_split = 0
        for i, chunk in enumerate(combined):
            children = _refine(
                chunk,
                ref_index=ref_index,
                config=config,
                tokenizer=tokenizer,
                validation_report=identity.validation_report,
            )
            if len(children) > 1:
                for child in children:
                    child.parent_chunk_key = pre_refine_ids[i]
                recursively_split += 1
            refined.extend(children)
        timings["refinement_s"] = time.perf_counter() - started

        # --- 3. Safe small-sibling merging --------------------------------------
        bind_run_context(context, stage="merging")
        started = time.perf_counter()
        merged = merge_small_chunks(refined, config=config, tokenizer=tokenizer, document_id=document_id)
        merge_count = sum(1 for c in merged if c.merged_from_keys)
        timings["merging_s"] = time.perf_counter() - started

        # --- 4. Stable IDs + navigation links -----------------------------------
        bind_run_context(context, stage="finalize")
        chunks = finalize_chunks(
            merged,
            document_id=document_id,
            source_filename=identity.source_filename,
            source_sha256=identity.source_sha256,
            tokenizer_name=config.tokenizer.name,
            include_heading_context=config.include_heading_context,
        )

        # --- 5. Export chunks.jsonl (atomic) ------------------------------------
        bind_run_context(context, stage="export")
        chunks_path = run.write_jsonl_atomic("chunks.jsonl", [c.model_dump(mode="json") for c in chunks])

        # --- 6. Validation -------------------------------------------------------
        bind_run_context(context, stage="validation")
        started = time.perf_counter()
        report = validate_chunks(
            chunks,
            doc=doc,
            document_id=document_id,
            source_sha256=identity.source_sha256,
            config=config,
            chunks_jsonl_path=chunks_path,
        )
        run.write_json_atomic("validation_report.json", report.model_dump(mode="json"))
        timings["validation_s"] = time.perf_counter() - started

        # --- 7. Manifest -----------------------------------------------------------
        bind_run_context(context, stage="manifest")
        content_type_counts: dict[str, int] = {}
        for c in chunks:
            content_type_counts[c.content_type.value] = content_type_counts.get(c.content_type.value, 0) + 1
        token_counts = [c.token_count for c in chunks]
        token_stats = _token_stats(token_counts)

        manifest = ChunkManifest(
            run_id=run.root.name,
            chunker_version=CHUNKER_VERSION,
            generated_at_utc=datetime.now(timezone.utc),
            source={
                "filename": identity.source_filename,
                "sha256": identity.source_sha256,
                "document_json_path": str(identity.document_json_path),
                "document_json_sha256": identity.document_json_sha256,
            },
            config_hash=config.config_hash(),
            effective_config=config.effective_dict(),
            tokenizer={"name": config.tokenizer.name, "max_tokens": config.max_tokens},
            chunk_count=len(chunks),
            content_type_counts=content_type_counts,
            token_stats=token_stats,
            recursively_split_count=sum(1 for c in chunks if c.was_recursively_split),
            merged_count=merge_count,
            warnings=[w for c in chunks for w in c.warnings],
            artifacts={
                "chunks.jsonl": sha256_file(chunks_path),
                "validation_report.json": sha256_file(run.path_for("validation_report.json")),
            },
            versions=_versions(),
            status=report.status.value,
            timings_s={k: round(v, 3) for k, v in timings.items()},
        )
        run.write_json_atomic("manifest.json", manifest.model_dump(mode="json"))

        summary_md = render_summary_markdown(manifest=manifest, report=report, config=config)
        run.write_text_atomic("chunking_summary.md", summary_md)

        bind_run_context(context, stage="complete")
        logger.info(
            "Chunking complete: %s -> %s (%d chunks, %d recursively split, %d merged)",
            report.status.value,
            run.root,
            len(chunks),
            manifest.recursively_split_count,
            merge_count,
        )
        return ChunkerResult(
            run_dir=run.root,
            status=report.status.value,
            chunk_count=len(chunks),
            manifest=manifest,
            chunks=chunks,
            timings=timings,
        )


def _token_stats(counts: list[int]) -> dict[str, float]:
    if not counts:
        return {"min": 0, "max": 0, "mean": 0, "median": 0, "p95": 0}
    sorted_counts = sorted(counts)
    n = len(sorted_counts)
    mean = sum(sorted_counts) / n
    median = sorted_counts[n // 2] if n % 2 else (sorted_counts[n // 2 - 1] + sorted_counts[n // 2]) / 2
    p95_index = min(n - 1, int(round(0.95 * (n - 1))))
    return {
        "min": float(sorted_counts[0]),
        "max": float(sorted_counts[-1]),
        "mean": round(mean, 2),
        "median": float(median),
        "p95": float(sorted_counts[p95_index]),
    }


def _versions() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version

    versions: dict[str, str] = {}
    for dist in ("docling-core", "transformers", "langchain-text-splitters"):
        try:
            versions[dist] = version(dist)
        except PackageNotFoundError:
            versions[dist] = "not-installed"
    return versions

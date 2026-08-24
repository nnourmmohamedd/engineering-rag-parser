"""Table refinement: row-aware splitting with repeated headers.

Tables are structured information, not prose. A table that fits stays whole.
An oversized table is split by logical row groups, never inside a cell
(unless one individual cell alone exceeds ``max_tokens``, in which case it
ships as an explicitly flagged atomic-overflow fragment rather than being
corrupted).
"""

from __future__ import annotations

import logging
from typing import Any

from docling_core.types.doc import DoclingDocument, TableItem

from engineering_rag.services.chunker.config import ChunkerConfig
from engineering_rag.services.chunker.internal import WorkingChunk
from engineering_rag.services.chunker.models import (
    ContentType,
    ProvenanceRecord,
    SplitMethod,
    TableFragmentMeta,
)
from engineering_rag.services.chunker.tokenizer import ChunkTokenizer

__all__ = ["build_uncovered_table_chunks", "refine_table_chunk"]

logger = logging.getLogger(__name__)


def _column_headers(table: TableItem) -> dict[int, str]:
    headers: dict[int, str] = {}
    for cell in table.data.table_cells:
        if cell.column_header:
            for c in range(cell.start_col_offset_idx, cell.end_col_offset_idx):
                headers.setdefault(c, (cell.text or "").strip())
    return headers


def _row_text(row_idx: int, cells_by_row: dict[int, list[Any]], headers: dict[int, str]) -> str:
    parts = []
    for cell in cells_by_row.get(row_idx, []):
        label = headers.get(cell.start_col_offset_idx, f"col{cell.start_col_offset_idx}")
        value = (cell.text or "").strip()
        if value:
            parts.append(f"{label}={value}")
    return "; ".join(parts)


def _propagate_parser_table_warnings(chunk: WorkingChunk, validation_report: dict[str, Any]) -> None:
    table_ref = chunk.source_element_refs[0] if chunk.source_element_refs else None
    for finding in validation_report.get("tables", []) or []:
        if finding.get("self_ref") != table_ref:
            continue
        for note in finding.get("notes", []) or []:
            if note not in chunk.parser_warnings:
                chunk.parser_warnings.append(note)


def refine_table_chunk(
    chunk: WorkingChunk,
    *,
    ref_index: dict[str, Any],
    config: ChunkerConfig,
    tokenizer: ChunkTokenizer,
    validation_report: dict[str, Any],
) -> list[WorkingChunk]:
    """Split one hierarchical TABLE chunk into row-group fragments if oversized."""
    _propagate_parser_table_warnings(chunk, validation_report)

    token_count = tokenizer.count(chunk.text)
    if token_count <= config.max_tokens:
        chunk.token_count = token_count
        return [chunk]

    table_ref = chunk.source_element_refs[0] if chunk.source_element_refs else None
    table = ref_index.get(table_ref) if table_ref else None
    if not isinstance(table, TableItem) or table.data.num_rows == 0:
        # No cell data to split by row (e.g. an unrecovered raster table whose
        # only content is a long caption) - keep whole as flagged overflow
        # rather than fabricating a split.
        chunk.token_count = token_count
        chunk.is_atomic_overflow = True
        chunk.warnings.append(
            f"Table chunk measures {token_count} tokens (> max_tokens={config.max_tokens}) with no "
            "recoverable cell data to split by row; kept as a single flagged oversized chunk."
        )
        return [chunk]

    headers = _column_headers(table)
    cells_by_row: dict[int, list[Any]] = {}
    header_rows: set[int] = set()
    for cell in table.data.table_cells:
        cells_by_row.setdefault(cell.start_row_offset_idx, []).append(cell)
        if cell.column_header:
            header_rows.add(cell.start_row_offset_idx)
    body_rows = sorted(r for r in cells_by_row if r not in header_rows)

    header_line = " | ".join(headers[c] or f"col{c}" for c in sorted(headers)) if headers else ""
    header_tokens = tokenizer.count(header_line) if config.repeat_table_headers and header_line else 0

    caption_prefix = "\n".join(chunk.captions) + "\n" if chunk.captions else ""

    fragments: list[list[int]] = []
    current: list[int] = []
    current_tokens = header_tokens
    for row_idx in body_rows:
        line = _row_text(row_idx, cells_by_row, headers)
        line_tokens = tokenizer.count(line)
        budget = config.max_tokens - (header_tokens if config.repeat_table_headers else 0)
        if line_tokens > budget:
            # A single row alone (with the repeated header) does not fit.
            if current:
                fragments.append(current)
                current = []
                current_tokens = header_tokens
            fragments.append([row_idx])  # oversized row ships alone, flagged below
            continue
        if current and current_tokens + line_tokens > config.max_tokens:
            fragments.append(current)
            current = []
            current_tokens = header_tokens
        current.append(row_idx)
        current_tokens += line_tokens
    if current:
        fragments.append(current)
    if not fragments:
        fragments = [[]]

    total = len(fragments)
    children: list[WorkingChunk] = []
    for frag_index, row_group in enumerate(fragments):
        include_header = bool(header_line) and (frag_index == 0 or config.repeat_table_headers)
        lines = [header_line] if include_header else []
        body_lines = [_row_text(r, cells_by_row, headers) for r in row_group]
        text = (
            caption_prefix + "\n".join([*lines, *body_lines])
            if frag_index == 0
            else "\n".join([*lines, *body_lines])
        )
        frag_tokens = tokenizer.count(text)
        overflow = frag_tokens > config.max_tokens
        child = WorkingChunk(
            text=text,
            content_type=chunk.content_type,
            heading_path=list(chunk.heading_path),
            section_title=chunk.section_title,
            captions=list(chunk.captions),
            labels=list(chunk.labels),
            page_numbers=list(chunk.page_numbers),
            provenance=list(chunk.provenance),
            source_element_refs=list(chunk.source_element_refs),
            split_method=SplitMethod.TABLE_ROWS,
            token_count=frag_tokens,
            is_atomic_overflow=overflow,
            table_metadata=TableFragmentMeta(
                num_rows=len(row_group),
                num_cols=table.data.num_cols,
                is_fragment=True,
                fragment_index=frag_index,
                total_fragments=total,
                header_repeated=config.repeat_table_headers and bool(header_line),
            ),
            parser_warnings=list(chunk.parser_warnings),
        )
        if overflow:
            child.warnings.append(
                f"Table row-group fragment {frag_index + 1}/{total} still measures {frag_tokens} tokens "
                f"(> max_tokens={config.max_tokens}); it contains a single row/cell too large to split "
                "further without corrupting cell content, so it is kept as a flagged oversized fragment."
            )
        children.append(child)

    logger.debug("Table split: %d token table -> %d row-group fragment(s)", token_count, len(children))
    return children


def _table_titles_by_label(validation_report: dict[str, Any]) -> dict[str, str]:
    """Titles for 'Table N' labels, from the parser's `labelled_tables_located` gate evidence.

    Docling's own `caption_text()` is empty for a table whose caption is
    plain body text rather than a structurally-linked caption item (the
    common case for a raster table with no text layer) — the parser's own
    native-PDF-text-based label discovery is the only place this title
    exists, so it is read from there instead of re-deriving it.
    """
    titles: dict[str, str] = {}
    for check in validation_report.get("checks", []) or []:
        if check.get("check_id") != "labelled_tables_located":
            continue
        for number, info in (check.get("evidence", {}).get("tables", {}) or {}).items():
            titles[f"Table {number}"] = info.get("title", "")
    return titles


def build_uncovered_table_chunks(
    doc: DoclingDocument,
    *,
    covered_refs: set[str],
    config: ChunkerConfig,
    tokenizer: ChunkTokenizer,
    validation_report: dict[str, Any],
) -> list[WorkingChunk]:
    """One TABLE chunk for every table Docling's HierarchicalChunker silently dropped.

    A table with no cells recovered *and* no Docling caption item (a raster
    table whose caption is plain nearby text, not a linked caption element)
    serializes to empty text and is skipped entirely by HierarchicalChunker —
    exactly the same blind spot :mod:`.figures` works around for pictures.
    """
    findings_by_ref = {f.get("self_ref"): f for f in validation_report.get("tables", []) or []}
    titles = _table_titles_by_label(validation_report)
    chunks: list[WorkingChunk] = []

    for table in doc.tables:
        if table.self_ref in covered_refs:
            continue
        finding = findings_by_ref.get(table.self_ref, {})
        label = finding.get("detected_label")
        title = titles.get(label, "") if label else ""
        caption = f"{label}: {title}" if label and title else (label or "")
        page_no = finding.get("page_no")
        text = caption or f"[Table on page {page_no}: no caption or recoverable cell data available]"

        provenance: list[ProvenanceRecord] = []
        for prov in table.prov or []:
            bbox = prov.bbox
            provenance.append(
                ProvenanceRecord(
                    page_no=int(prov.page_no),
                    bbox=(float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b)) if bbox else None,
                )
            )
        if not provenance and page_no is not None:
            provenance.append(ProvenanceRecord(page_no=int(page_no)))

        token_count = tokenizer.count(text)
        chunks.append(
            WorkingChunk(
                text=text,
                content_type=ContentType.TABLE,
                heading_path=[],
                section_title=None,
                captions=[caption] if caption else [],
                labels=[table.label.value],
                page_numbers=sorted({p.page_no for p in provenance}),
                provenance=provenance,
                source_element_refs=[table.self_ref],
                split_method=SplitMethod.TABLE_ROWS,
                token_count=token_count,
                is_atomic_overflow=token_count > config.max_tokens,
                table_metadata=TableFragmentMeta(
                    num_rows=int(table.data.num_rows), num_cols=int(table.data.num_cols), detected_label=label
                ),
                parser_warnings=list(finding.get("notes", []) or []),
                warnings=(
                    ["No cells recovered and no source caption available for this table region."]
                    if not caption and table.data.num_rows == 0
                    else []
                ),
            )
        )

    if chunks:
        logger.info(
            "Recovered %d table(s) HierarchicalChunker had dropped (empty serialized text).", len(chunks)
        )
    return chunks

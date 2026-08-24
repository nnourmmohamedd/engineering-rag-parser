"""Final stage: assign chunk_index, stable IDs, and previous/next navigation links.

Runs last, once ordering is fixed by every prior stage (hierarchical order,
then in-place refinement, then merging never reorders).
"""

from __future__ import annotations

from .ids import chunk_id
from .internal import WorkingChunk
from .models import Chunk

__all__ = ["finalize_chunks"]


def finalize_chunks(
    chunks: list[WorkingChunk],
    *,
    document_id: str,
    source_filename: str,
    source_sha256: str,
    tokenizer_name: str,
    include_heading_context: bool,
) -> list[Chunk]:
    """Convert working chunks into the final, versioned, linked output records."""
    ids = [chunk_id(document_id_=document_id, chunk_index=i, text=c.text) for i, c in enumerate(chunks)]

    finalized: list[Chunk] = []
    for i, working in enumerate(chunks):
        finalized.append(
            Chunk(
                chunk_id=ids[i],
                document_id=document_id,
                source_filename=source_filename,
                source_sha256=source_sha256,
                chunk_index=i,
                content_type=working.content_type,
                text=working.text,
                retrieval_text=working.retrieval_text(include_heading_context=include_heading_context),
                token_count=working.token_count,
                tokenizer_name=tokenizer_name,
                heading_path=working.heading_path,
                section_title=working.section_title,
                captions=working.captions,
                labels=working.labels,
                page_numbers=working.page_numbers,
                provenance=working.provenance,
                source_element_refs=working.source_element_refs,
                parent_chunk_id=working.parent_chunk_key,
                previous_chunk_id=ids[i - 1] if i > 0 else None,
                next_chunk_id=ids[i + 1] if i < len(chunks) - 1 else None,
                merged_from_chunk_ids=working.merged_from_keys,
                split_method=working.split_method,
                was_recursively_split=working.was_recursively_split,
                overlap_tokens_before=working.overlap_tokens_before,
                table_metadata=working.table_metadata,
                figure_asset_path=working.figure_asset_path,
                figure_page_no=working.figure_page_no,
                is_atomic_overflow=working.is_atomic_overflow,
                parser_warnings=working.parser_warnings,
                warnings=working.warnings,
            )
        )
    return finalized

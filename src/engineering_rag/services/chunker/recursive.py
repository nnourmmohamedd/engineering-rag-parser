"""Stage: controlled recursive splitting of oversized TEXT chunks only.

Recursive splitting is applied **only** when a hierarchical TEXT chunk
exceeds ``max_tokens`` — never blindly to the whole flattened document, and
never to tables, figures, equations or code (those have their own
type-specific handlers in :mod:`.type_handlers`). See
``docs/chunker/MENTOR_EXPLANATION.md`` for the rationale.
"""

from __future__ import annotations

import logging

from langchain_text_splitters import RecursiveCharacterTextSplitter

from .config import ChunkerConfig
from .internal import WorkingChunk
from .models import ContentType, SplitMethod
from .tokenizer import ChunkTokenizer

__all__ = ["split_oversized_text_chunk"]

logger = logging.getLogger(__name__)


def split_oversized_text_chunk(
    chunk: WorkingChunk, *, config: ChunkerConfig, tokenizer: ChunkTokenizer
) -> list[WorkingChunk]:
    """Split one oversized TEXT chunk into deterministically-ordered children.

    Returns ``[chunk]`` unchanged (with ``token_count`` set) if it already
    fits within ``max_tokens`` — recursive splitting never runs on a chunk
    that already fits.
    """
    if chunk.content_type is not ContentType.TEXT:
        raise ValueError(f"split_oversized_text_chunk only accepts TEXT chunks, got {chunk.content_type}")

    token_count = tokenizer.count(chunk.text)
    if token_count <= config.max_tokens:
        chunk.token_count = token_count
        return [chunk]

    splitter = RecursiveCharacterTextSplitter(
        separators=list(config.recursive_separators),
        chunk_size=config.target_tokens,
        chunk_overlap=config.text_overlap_tokens,
        length_function=tokenizer.length_function(),
        keep_separator="end",
    )
    segments = splitter.split_text(chunk.text)
    if not segments:
        # Degenerate input (e.g. all whitespace after stripping separators):
        # keep the original as a single atomic-overflow chunk rather than
        # producing zero chunks and silently losing the content.
        chunk.token_count = token_count
        chunk.is_atomic_overflow = True
        chunk.warnings.append(
            f"Text chunk measures {token_count} tokens (> max_tokens={config.max_tokens}) but the "
            "recursive splitter produced no segments; kept as a single flagged oversized chunk."
        )
        return [chunk]

    children: list[WorkingChunk] = []
    for i, segment in enumerate(segments):
        seg_tokens = tokenizer.count(segment)
        overflow = seg_tokens > config.max_tokens
        child = WorkingChunk(
            text=segment,
            content_type=ContentType.TEXT,
            heading_path=list(chunk.heading_path),
            section_title=chunk.section_title,
            captions=list(chunk.captions),
            labels=list(chunk.labels),
            page_numbers=list(chunk.page_numbers),
            provenance=list(chunk.provenance),
            source_element_refs=list(chunk.source_element_refs),
            split_method=SplitMethod.RECURSIVE_TEXT,
            was_recursively_split=True,
            overlap_tokens_before=config.text_overlap_tokens if i > 0 else 0,
            token_count=seg_tokens,
            is_atomic_overflow=overflow,
        )
        if overflow:
            child.warnings.append(
                f"Recursively-split segment still measures {seg_tokens} tokens (> "
                f"max_tokens={config.max_tokens}); it contains no smaller separator boundary "
                "(a single very long word/token run) so it is kept as a flagged oversized chunk "
                "rather than corrupted by an arbitrary character cut."
            )
        children.append(child)

    logger.debug(
        "Recursive split: %d token chunk -> %d children (target=%d, overlap=%d)",
        token_count,
        len(children),
        config.target_tokens,
        config.text_overlap_tokens,
    )
    return children

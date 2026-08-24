"""Code refinement: split on line boundaries only, indentation preserved verbatim."""

from __future__ import annotations

import logging

from engineering_rag.services.chunker.config import ChunkerConfig
from engineering_rag.services.chunker.internal import WorkingChunk
from engineering_rag.services.chunker.models import SplitMethod
from engineering_rag.services.chunker.tokenizer import ChunkTokenizer

__all__ = ["refine_code_chunk"]

logger = logging.getLogger(__name__)


def refine_code_chunk(
    chunk: WorkingChunk, *, config: ChunkerConfig, tokenizer: ChunkTokenizer
) -> list[WorkingChunk]:
    """Split one hierarchical CODE chunk on line boundaries if oversized.

    Lines are never altered — no re-indentation, no stripping — only grouped.
    """
    token_count = tokenizer.count(chunk.text)
    if token_count <= config.max_tokens:
        chunk.token_count = token_count
        return [chunk]

    lines = chunk.text.split("\n")
    if len(lines) <= 1:
        chunk.token_count = token_count
        chunk.is_atomic_overflow = True
        chunk.warnings.append(
            f"Code chunk measures {token_count} tokens (> max_tokens={config.max_tokens}) but is a "
            "single line with no line boundary to split on; kept as a single flagged oversized chunk."
        )
        return [chunk]

    groups: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0
    for line in lines:
        line_tokens = tokenizer.count(line)
        if current and current_tokens + line_tokens > config.max_tokens:
            groups.append(current)
            current = []
            current_tokens = 0
        current.append(line)
        current_tokens += line_tokens
    if current:
        groups.append(current)

    children: list[WorkingChunk] = []
    for group in groups:
        text = "\n".join(group)
        tokens = tokenizer.count(text)
        children.append(
            WorkingChunk(
                text=text,
                content_type=chunk.content_type,
                heading_path=list(chunk.heading_path),
                section_title=chunk.section_title,
                captions=list(chunk.captions),
                labels=list(chunk.labels),
                page_numbers=list(chunk.page_numbers),
                provenance=list(chunk.provenance),
                source_element_refs=list(chunk.source_element_refs),
                split_method=SplitMethod.CODE_BLOCK,
                token_count=tokens,
                is_atomic_overflow=tokens > config.max_tokens,
            )
        )
    logger.debug("Code split: %d token block -> %d line-group(s)", token_count, len(children))
    return children

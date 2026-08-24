"""List refinement: split between list items, never mid-item."""

from __future__ import annotations

import logging

from engineering_rag.services.chunker.config import ChunkerConfig
from engineering_rag.services.chunker.internal import WorkingChunk
from engineering_rag.services.chunker.models import SplitMethod
from engineering_rag.services.chunker.tokenizer import ChunkTokenizer

__all__ = ["refine_list_chunk"]

logger = logging.getLogger(__name__)


def refine_list_chunk(
    chunk: WorkingChunk, *, config: ChunkerConfig, tokenizer: ChunkTokenizer
) -> list[WorkingChunk]:
    """Split one hierarchical LIST chunk between items if oversized."""
    token_count = tokenizer.count(chunk.text)
    if token_count <= config.max_tokens:
        chunk.token_count = token_count
        return [chunk]

    items = [line for line in chunk.text.split("\n") if line.strip()]
    if len(items) <= 1:
        chunk.token_count = token_count
        chunk.is_atomic_overflow = True
        chunk.warnings.append(
            f"List chunk measures {token_count} tokens (> max_tokens={config.max_tokens}) but has no "
            "item boundary to split on; kept as a single flagged oversized chunk."
        )
        return [chunk]

    groups: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0
    for item in items:
        item_tokens = tokenizer.count(item)
        if current and current_tokens + item_tokens > config.max_tokens:
            groups.append(current)
            current = []
            current_tokens = 0
        current.append(item)
        current_tokens += item_tokens
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
                split_method=SplitMethod.LIST_ITEMS,
                token_count=tokens,
                is_atomic_overflow=tokens > config.max_tokens,
            )
        )
    logger.debug("List split: %d token list -> %d item-group(s)", token_count, len(children))
    return children

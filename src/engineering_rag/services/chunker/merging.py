"""Stage: safe small-sibling merging.

Only TEXT and LIST chunks are ever merge candidates — tables, figures,
equations and code carry structural or atomic semantics a generic merge could
silently destroy, so they are never merge targets, regardless of size.

All safety conditions must hold simultaneously:

- same content type (TEXT or LIST only);
- same heading/section path;
- adjacent in reading order (guaranteed — chunks are visited in document order);
- combined token count stays within ``max_tokens``;
- at least one side is undersized (< ``min_chunk_tokens``) — merging two
  already-adequately-sized chunks would not improve retrieval quality and
  only adds risk.
"""

from __future__ import annotations

import logging

from .config import ChunkerConfig
from .internal import WorkingChunk
from .linking import provisional_ids
from .models import ContentType, SplitMethod
from .tokenizer import ChunkTokenizer

__all__ = ["merge_small_chunks"]

logger = logging.getLogger(__name__)

_MERGEABLE_TYPES = frozenset({ContentType.TEXT, ContentType.LIST})


def _can_merge(a: WorkingChunk, b: WorkingChunk, *, config: ChunkerConfig) -> bool:
    if a.content_type not in _MERGEABLE_TYPES or a.content_type != b.content_type:
        return False
    if a.heading_path != b.heading_path:
        return False
    if a.token_count >= config.min_chunk_tokens and b.token_count >= config.min_chunk_tokens:
        return False  # neither side is undersized: no reason to merge
    return a.token_count + b.token_count <= config.max_tokens


def _merged(a: WorkingChunk, b: WorkingChunk, *, tokenizer: ChunkTokenizer, ids: list[str]) -> WorkingChunk:
    text = "\n\n".join([a.text, b.text])
    return WorkingChunk(
        text=text,
        content_type=a.content_type,
        heading_path=list(a.heading_path),
        section_title=a.section_title,
        captions=[*a.captions, *[c for c in b.captions if c not in a.captions]],
        labels=sorted(set(a.labels) | set(b.labels)),
        page_numbers=sorted(set(a.page_numbers) | set(b.page_numbers)),
        provenance=[*a.provenance, *b.provenance],
        source_element_refs=[*a.source_element_refs, *b.source_element_refs],
        split_method=SplitMethod.MERGED,
        token_count=tokenizer.count(text),
        merged_from_keys=ids,
        parser_warnings=sorted(set(a.parser_warnings) | set(b.parser_warnings)),
    )


def merge_small_chunks(
    chunks: list[WorkingChunk], *, config: ChunkerConfig, tokenizer: ChunkTokenizer, document_id: str
) -> list[WorkingChunk]:
    """Merge undersized adjacent compatible chunks, deterministically."""
    if not config.merge_small_chunks or not chunks:
        return chunks

    pre_merge_ids = provisional_ids(chunks, document_id=document_id)
    merged: list[WorkingChunk] = []
    merge_count = 0

    current = chunks[0]
    current_source_ids = [pre_merge_ids[0]]
    for i in range(1, len(chunks)):
        nxt = chunks[i]
        if _can_merge(current, nxt, config=config):
            current = _merged(current, nxt, tokenizer=tokenizer, ids=[*current_source_ids, pre_merge_ids[i]])
            current_source_ids = current.merged_from_keys or []
            merge_count += 1
        else:
            merged.append(current)
            current = nxt
            current_source_ids = [pre_merge_ids[i]]
    merged.append(current)

    if merge_count:
        logger.info(
            "Small-sibling merging: %d merge(s), %d -> %d chunk(s)", merge_count, len(chunks), len(merged)
        )
    return merged

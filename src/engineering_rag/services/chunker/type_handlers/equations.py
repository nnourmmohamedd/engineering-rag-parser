"""Equation refinement: atomic only — an equation is never split.

If a single equation's text (plus its heading context) exceeds ``max_tokens``,
it ships as an explicitly flagged atomic-overflow chunk rather than being
corrupted by a mid-equation cut.
"""

from __future__ import annotations

import logging

from engineering_rag.services.chunker.config import ChunkerConfig
from engineering_rag.services.chunker.internal import WorkingChunk
from engineering_rag.services.chunker.tokenizer import ChunkTokenizer

__all__ = ["refine_equation_chunk"]

logger = logging.getLogger(__name__)


def refine_equation_chunk(
    chunk: WorkingChunk, *, config: ChunkerConfig, tokenizer: ChunkTokenizer
) -> list[WorkingChunk]:
    """Measure one hierarchical EQUATION chunk; never split it."""
    token_count = tokenizer.count(chunk.text)
    chunk.token_count = token_count
    if token_count > config.max_tokens:
        chunk.is_atomic_overflow = True
        chunk.warnings.append(
            f"Equation chunk measures {token_count} tokens (> max_tokens={config.max_tokens}); "
            "equations are never split, so this ships as a single flagged oversized chunk."
        )
    return [chunk]

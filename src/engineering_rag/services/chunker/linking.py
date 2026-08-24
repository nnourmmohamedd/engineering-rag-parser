"""Deterministic lineage tracking across pipeline stages.

Recursive splitting and small-sibling merging both replace one or more
:class:`~.internal.WorkingChunk`\\ s with a different set. This module assigns
each pre-transformation chunk a stable *provisional* ID (from its position in
that stage and its own text) so children/merged results can record
``parent_chunk_key`` / ``merged_from_keys`` deterministically, without those
provisional rows needing to exist as separate output lines.
"""

from __future__ import annotations

from .ids import chunk_id
from .internal import WorkingChunk

__all__ = ["provisional_ids"]


def provisional_ids(chunks: list[WorkingChunk], *, document_id: str) -> list[str]:
    """A stable ID per chunk, from its position in ``chunks`` and its own text."""
    return [chunk_id(document_id_=document_id, chunk_index=i, text=c.text) for i, c in enumerate(chunks)]

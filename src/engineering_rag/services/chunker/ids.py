"""Deterministic chunk and document identifiers.

No random UUIDs anywhere: an identical (input, config) pair must always
produce byte-identical IDs, which is what makes ``chunks.jsonl`` reproducible
across repeated runs.
"""

from __future__ import annotations

import hashlib

__all__ = ["chunk_id", "document_id"]


def document_id(source_sha256: str) -> str:
    """Stable document identity: the source PDF's own SHA-256, unchanged."""
    return source_sha256


def chunk_id(*, document_id_: str, chunk_index: int, text: str) -> str:
    """Stable chunk identity derived from document identity, position and content.

    Content is included (not just position) so that a chunk whose content
    changed under an edited configuration gets a new ID rather than silently
    reusing a stale one at the same index; position is included so that two
    chunks with coincidentally identical text at different positions do not
    collide.
    """
    payload = f"{document_id_}|{chunk_index}|{text}".encode()
    digest = hashlib.sha256(payload).hexdigest()
    return f"chunk_{digest[:16]}"

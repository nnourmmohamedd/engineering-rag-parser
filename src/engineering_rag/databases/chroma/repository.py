"""Idempotent ingestion repository: batch writes + per-record content-hash conflict detection.

Reindexing identical input must never duplicate. The rule, implemented here:

- same id, same content hash on the collection already -> skip (idempotent no-op)
- same id, *different* content hash -> hard failure (:class:`DuplicateIdConflictError`),
  never a silent overwrite
- ids not present at all -> inserted

The caller (the indexing pipeline) is responsible for batching this call at
``config.ingestion_batch_size`` and for validating the collection identity
*before* any write (see ``collection.open_or_create_collection``), so no
record from an incompatible collection is ever written.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from .errors import DuplicateIdConflictError
from .models import IngestionOutcome

__all__ = ["content_hash", "ingest_batch"]

logger = logging.getLogger(__name__)


def content_hash(retrieval_text: str, metadata: dict[str, Any]) -> str:
    """Stable hash of a record's content: retrieval_text + key metadata.

    Stored in each record's own metadata (``content_hash``) so a rerun can
    tell "unchanged, skip" from "changed under the same id, hard fail" without
    re-embedding or re-fetching the vector.
    """
    payload = retrieval_text + "|" + "|".join(f"{k}={metadata[k]}" for k in sorted(metadata))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ingest_batch(
    collection: Any,  # chromadb.Collection
    *,
    ids: list[str],
    embeddings: list[list[float]],
    documents: list[str],
    metadatas: list[dict[str, Any]],
    idempotent: bool,
) -> IngestionOutcome:
    """Write one batch, resolving idempotent-skip vs conflicting-duplicate per id.

    ``metadatas[i]`` must already contain a ``content_hash`` key (see
    :func:`content_hash`) — this function does not compute it.
    """
    outcome = IngestionOutcome(expected_ids=list(ids))
    if not ids:
        return outcome

    existing = collection.get(ids=ids, include=["metadatas"])
    existing_hashes = {
        eid: (emeta or {}).get("content_hash")
        for eid, emeta in zip(existing["ids"], existing["metadatas"] or [], strict=True)
    }

    to_write_idx: list[int] = []
    for i, cid in enumerate(ids):
        if cid in existing_hashes:
            new_hash = metadatas[i].get("content_hash")
            if existing_hashes[cid] == new_hash:
                outcome.existing_identical_ids.append(cid)
                continue
            if idempotent:
                raise DuplicateIdConflictError(
                    f"id {cid!r} already exists in the collection with a different content hash "
                    f"(existing={existing_hashes[cid]!r}, new={new_hash!r}). Refusing to silently "
                    "overwrite; use --rebuild for a destructive replacement."
                )
            outcome.rejected_ids.append(cid)
            continue
        to_write_idx.append(i)

    if to_write_idx:
        collection.upsert(
            ids=[ids[i] for i in to_write_idx],
            embeddings=[embeddings[i] for i in to_write_idx],
            documents=[documents[i] for i in to_write_idx],
            metadatas=[metadatas[i] for i in to_write_idx],
        )
        outcome.inserted_ids = [ids[i] for i in to_write_idx]

    outcome.final_count = collection.count()
    return outcome

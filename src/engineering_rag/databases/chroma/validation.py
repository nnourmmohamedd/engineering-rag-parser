"""Storage-level validation: round-trip integrity and self-retrieval.

These are Chroma-adapter-level checks (operate on a live collection);
higher-level gates that combine these with chunk-run/embedder concerns live
in :mod:`engineering_rag.pipelines.indexing_pipeline`.
"""

from __future__ import annotations

import math
from typing import Any

__all__ = ["round_trip_check", "self_retrieval_check"]


def round_trip_check(
    collection: Any,
    *,
    ids: list[str],
    expected_documents: dict[str, str],
    norm_tolerance: float,
) -> list[str]:
    """Fetch ``ids`` back from ``collection`` and verify document/vector integrity.

    Returns a list of human-readable problem descriptions (empty = all good).
    """
    problems: list[str] = []
    if not ids:
        return problems
    got = collection.get(ids=ids, include=["documents", "embeddings", "metadatas"])
    got_by_id = dict(
        zip(got["ids"], zip(got["documents"], got["embeddings"], got["metadatas"], strict=True), strict=True)
    )

    for cid in ids:
        if cid not in got_by_id:
            problems.append(f"{cid}: missing from collection on round-trip fetch")
            continue
        doc, vec, _meta = got_by_id[cid]
        expected_doc = expected_documents.get(cid)
        if expected_doc is not None and doc != expected_doc:
            problems.append(f"{cid}: stored document does not equal retrieval_text")
        if vec is None or len(vec) == 0:
            problems.append(f"{cid}: missing embedding on round-trip fetch")
            continue
        norm = math.sqrt(sum(float(v) * float(v) for v in vec))
        if abs(norm - 1.0) > norm_tolerance:
            problems.append(f"{cid}: round-tripped vector norm {norm:.6f} not within {norm_tolerance} of 1.0")
    return problems


def self_retrieval_check(
    collection: Any,
    *,
    sample_ids: list[str],
    vectors_by_id: dict[str, list[float]],
) -> list[str]:
    """Query each sampled id's own stored vector; verify it comes back at rank 1.

    Returns a list of human-readable failures (empty = all sampled ids
    self-retrieved correctly, modulo documented exact-vector ties).
    """
    failures: list[str] = []
    for cid in sample_ids:
        vector = vectors_by_id.get(cid)
        if vector is None:
            failures.append(f"{cid}: no stored vector available for self-retrieval test")
            continue
        result = collection.query(query_embeddings=[vector], n_results=1, include=["distances"])
        result_ids = result["ids"][0] if result["ids"] else []
        if not result_ids or result_ids[0] != cid:
            failures.append(f"{cid}: self-retrieval rank-1 mismatch, got {result_ids[:1]}")
    return failures

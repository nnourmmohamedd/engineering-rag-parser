"""BM25 lexical retrieval: loads a persistent index and ranks it against a query.

Mirrors ``VectorRetriever``: receives an already-loaded
:class:`~engineering_rag.databases.bm25.index.BM25IndexHandle` (dependency
injection — ``pipelines/retrieval_pipeline.py`` is the only module that
loads one) and never rebuilds or writes to the index while searching.

Metadata filtering limitation: ``bm25s`` has no native metadata filter.
Because the indexed corpus is small (currently 122 chunks), this retriever
scores the *entire* corpus every query (cheap — sub-millisecond for this
size) and applies the identical filter semantics Chroma uses
(``services/retriever/filters.py``'s allowed-field list: scalar equality,
or membership when the value is a list/tuple) client-side to the full
ranked list *before* truncating to ``top_k``. This preserves correct top-k
semantics (filtering never removes an already-truncated candidate) at the
cost of not scaling to a corpus where scoring everything is expensive —
documented here rather than silently degrading behavior at scale.

Because the filter is applied before truncation, a document-scoped query
genuinely ranks within the selected corpus; it is not a global search whose
disallowed rows are hidden afterwards.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from engineering_rag.databases.bm25.index import BM25IndexHandle
from engineering_rag.databases.bm25.models import BM25RawHit

from .config import RetrievalSearchConfig
from .errors import InvalidFilterError
from .models import FilterValue, RetrievalHit
from .retriever import _decode_provenance

__all__ = ["BM25Retriever", "BM25SearchOutcome"]

logger = logging.getLogger(__name__)


class BM25SearchOutcome:
    """One BM25 search's typed hits plus timing, kept separate from the fused response contract."""

    def __init__(self, hits: list[RetrievalHit], duration_s: float) -> None:
        self.hits = hits
        self.duration_s = duration_s


def _matches_one(actual: Any, expected: FilterValue) -> bool:
    """Mirror Chroma's semantics: a list/tuple means membership (``$in``), a scalar means equality."""
    if isinstance(expected, list | tuple):
        return any(str(actual) == str(candidate) for candidate in expected)
    return str(actual) == str(expected)


def _matches_filters(record_metadata: dict[str, Any], filters: dict[str, FilterValue]) -> bool:
    return all(_matches_one(record_metadata.get(key), value) for key, value in filters.items())


def _raw_hit_to_retrieval_hit(raw: BM25RawHit) -> RetrievalHit:
    record = raw.record
    return RetrievalHit(
        rank=raw.bm25_rank,
        chunk_id=record.chunk_id,
        retrieval_text=record.retrieval_text,
        raw_distance=0.0,
        document_id=record.document_id,
        source_filename=record.source_filename,
        source_sha256=record.source_sha256,
        page_numbers=list(record.page_numbers),
        section_title=record.section_title,
        heading_path=list(record.heading_path),
        content_type=record.content_type,
        content_hash=record.content_hash,
        bm25_rank=raw.bm25_rank,
        bm25_score=raw.bm25_score,
        provenance=_decode_provenance(record.metadata.get("provenance")),
        bbox_reliable=bool(record.metadata.get("bbox_reliable", False)),
        metadata=dict(record.metadata),
    )


class BM25Retriever:
    """Stateless-per-call lexical retrieval over one injected, already-loaded BM25 index."""

    def __init__(self, *, index: BM25IndexHandle, config: RetrievalSearchConfig) -> None:
        self._index = index
        self._config = config

    def search(
        self,
        query: str,
        top_k: int,
        metadata_filters: dict[str, FilterValue] | None = None,
    ) -> BM25SearchOutcome:
        """Rank the entire indexed corpus and return the top ``top_k`` matches (post-filter).

        An empty/whitespace query returns zero hits (a lexical index has
        nothing to match), which is not an error — unlike
        :class:`VectorRetriever`, which requires a non-empty query to embed.
        """
        filters = metadata_filters or {}
        allowed = set(self._config.allowed_metadata_filter_fields)
        unsupported = sorted(set(filters) - allowed)
        if unsupported:
            raise InvalidFilterError(
                f"unsupported metadata filter field(s): {unsupported}. Allowed fields: {sorted(allowed)}."
            )

        started = time.perf_counter()
        corpus_size = len(self._index.manifest.chunk_ids)
        raw_hits = self._index.search(query, top_k=max(corpus_size, top_k))

        filtered = (
            [h for h in raw_hits if _matches_filters(h.record.metadata, filters)] if filters else raw_hits
        )
        top = filtered[:top_k]

        hits: list[RetrievalHit] = []
        for rank, raw in enumerate(top, start=1):
            hit = _raw_hit_to_retrieval_hit(raw)
            hits.append(hit.model_copy(update={"rank": rank}))

        duration = time.perf_counter() - started
        return BM25SearchOutcome(hits=hits, duration_s=duration)

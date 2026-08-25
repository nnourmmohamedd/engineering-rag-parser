"""Core vector-retrieval domain logic: query embedding -> Chroma search -> provenance-preserving hits.

Receives an already-constructed :class:`~engineering_rag.services.embedder.interface.EmbeddingService`
and an already-opened Chroma collection object (dependency injection — see
``pipelines/retrieval_pipeline.py``, the only module that creates a Chroma
client or resolves a live embedder). This module never imports ``chromadb``
directly and never constructs its own client; it only calls methods on the
collection object it is handed, so it cannot mutate or create a collection as
a side effect of searching it.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from engineering_rag.services.embedder.errors import EmptyQueryError
from engineering_rag.services.embedder.interface import EmbeddingService

from .config import RetrievalSearchConfig
from .errors import (
    EmptyCollectionError,
    MalformedChromaResponseError,
    RetrievalError,
)
from .filters import build_where_clause
from .models import (
    RetrievalDiagnostics,
    RetrievalHit,
    RetrievalRequest,
    RetrievalResponse,
    query_hash,
)

__all__ = ["SearchableRetriever", "VectorRetriever"]

logger = logging.getLogger(__name__)


@runtime_checkable
class SearchableRetriever(Protocol):
    """Structural type shared by :class:`VectorRetriever` and the hybrid orchestrator.

    Lets ``services/retriever/evaluation/runner.py`` evaluate vector-only,
    hybrid, vector+rerank, and hybrid+rerank searches through the identical
    ``search(request) -> RetrievalResponse`` call, with no evaluation-side
    branching on which mode is active.
    """

    def search(self, request: RetrievalRequest) -> RetrievalResponse: ...


#: Chunk metadata fields that are JSON-encoded strings on write
#: (see ``databases/chroma/metadata.py``) and must be decoded back to lists.
_LIST_FIELDS = ("heading_path", "page_numbers", "source_element_refs")


def _decode_list_field(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return []
        return decoded if isinstance(decoded, list) else []
    return []


def _build_hit(
    rank: int, chunk_id: str, document: str, distance: float, metadata: dict[str, Any]
) -> RetrievalHit:
    meta = dict(metadata or {})
    return RetrievalHit(
        rank=rank,
        final_rank=rank,
        vector_rank=rank,
        chunk_id=chunk_id,
        retrieval_text=document or "",
        raw_distance=float(distance),
        document_id=meta.get("document_id"),
        source_filename=meta.get("source_filename"),
        source_sha256=meta.get("source_sha256"),
        page_numbers=[int(p) for p in _decode_list_field(meta.get("page_numbers"))],
        section_title=meta.get("section_title"),
        heading_path=[str(h) for h in _decode_list_field(meta.get("heading_path"))],
        content_type=meta.get("content_type"),
        chunk_index=meta.get("chunk_index"),
        previous_chunk_id=meta.get("previous_chunk_id"),
        next_chunk_id=meta.get("next_chunk_id"),
        source_element_refs=[str(r) for r in _decode_list_field(meta.get("source_element_refs"))],
        content_hash=meta.get("content_hash"),
        metadata=meta,
    )


class VectorRetriever:
    """Stateless-per-call retrieval: one injected embedder + one injected collection."""

    def __init__(
        self,
        *,
        embedder: EmbeddingService,
        collection: Any,  # chromadb.Collection, already opened by the caller
        config: RetrievalSearchConfig,
        collection_distance_metric: str,
    ) -> None:
        self._embedder = embedder
        self._collection = collection
        self._config = config
        self._distance_metric = collection_distance_metric

    def search(self, request: RetrievalRequest) -> RetrievalResponse:
        """Embed ``request.query``, search the injected collection, return provenance-preserving hits.

        Raises:
            RetrievalError: empty/whitespace/too-long query, or ``top_k`` out of bounds.
            InvalidFilterError: an unsupported metadata filter field or value type.
            EmptyCollectionError: the collection has zero records.
            MalformedChromaResponseError: Chroma returned arrays of mismatched length.
        """
        started = time.perf_counter()
        warnings: list[str] = []

        query = request.query
        if not query or not query.strip():
            raise RetrievalError("query must not be empty or whitespace-only")
        if len(query) > self._config.query_max_length_chars:
            raise RetrievalError(
                f"query is {len(query)} chars, exceeds the configured maximum of "
                f"{self._config.query_max_length_chars} chars"
            )
        if request.top_k > self._config.maximum_top_k:
            raise RetrievalError(
                f"requested top_k ({request.top_k}) exceeds the configured maximum ({self._config.maximum_top_k})"
            )

        try:
            record_count = self._collection.count()
        except Exception as exc:  # noqa: BLE001 - surface a clean RetrievalError
            raise RetrievalError(f"failed to read collection state: {exc}") from exc
        if record_count == 0:
            raise EmptyCollectionError(
                f"collection {self._collection.name!r} exists but contains zero records; nothing to search"
            )

        where = build_where_clause(request.metadata_filters, self._config)  # may raise InvalidFilterError

        embed_started = time.perf_counter()
        try:
            vector = self._embedder.embed_query(query)
        except EmptyQueryError as exc:
            raise RetrievalError(str(exc)) from exc
        embedding_duration = time.perf_counter() - embed_started

        db_started = time.perf_counter()
        try:
            result = self._collection.query(
                query_embeddings=[vector],
                n_results=request.top_k,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:  # noqa: BLE001 - surface a clean RetrievalError
            raise RetrievalError(f"Chroma query failed: {exc}") from exc
        database_duration = time.perf_counter() - db_started

        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        lengths = {len(ids), len(documents), len(metadatas), len(distances)}
        if len(lengths) > 1:
            raise MalformedChromaResponseError(
                f"Chroma returned mismatched array lengths: ids={len(ids)}, documents={len(documents)}, "
                f"metadatas={len(metadatas)}, distances={len(distances)}"
            )

        model_info = self._embedder.model_info()
        similarity_ok = self._distance_metric == "cosine"
        if not similarity_ok:
            warnings.append(
                f"collection distance_metric is {self._distance_metric!r}, not 'cosine'; "
                "similarity_score is not computed (raw_distance only)."
            )

        # Deterministic secondary ordering for exact-distance ties: Chroma
        # already returns rank order, but we stabilize ties by chunk_id so
        # repeated calls against the same data are byte-identical.
        rows = list(zip(ids, documents, metadatas, distances, strict=True))
        rows.sort(key=lambda r: (round(r[3], 12), r[0]))

        seen_ids: set[str] = set()
        hits: list[RetrievalHit] = []
        for rank, (cid, doc, meta, dist) in enumerate(rows, start=1):
            if cid in seen_ids:
                warnings.append(f"duplicate chunk_id {cid!r} returned by Chroma in one query; deduplicated")
                continue
            seen_ids.add(cid)
            hit = _build_hit(rank, cid, doc, dist, meta or {})
            if similarity_ok:
                hit = hit.model_copy(update={"similarity_score": 1.0 - hit.raw_distance})
            hits.append(hit)

        diagnostics = _build_diagnostics(hits)

        total_duration = time.perf_counter() - started
        return RetrievalResponse(
            query=query,
            query_hash=query_hash(query),
            collection_name=self._collection.name,
            requested_top_k=request.top_k,
            returned_count=len(hits),
            embedding_model=model_info.model_name,
            embedding_revision=model_info.resolved_revision,
            embedding_dimension=model_info.dimension,
            distance_metric=self._distance_metric,
            embedding_duration_s=round(embedding_duration, 6),
            database_duration_s=round(database_duration, 6),
            total_duration_s=round(total_duration, 6),
            hits=hits,
            diagnostics=diagnostics,
            warnings=warnings,
            generated_at_utc=datetime.now(timezone.utc),
        )


def _build_diagnostics(hits: list[RetrievalHit]) -> RetrievalDiagnostics:
    by_hash: dict[str, list[str]] = {}
    by_distance: dict[float, list[str]] = {}
    for hit in hits:
        if hit.content_hash:
            by_hash.setdefault(hit.content_hash, []).append(hit.chunk_id)
        by_distance.setdefault(round(hit.raw_distance, 12), []).append(hit.chunk_id)

    duplicate_hash_groups = [ids for ids in by_hash.values() if len(ids) > 1]
    tied_groups = [ids for ids in by_distance.values() if len(ids) > 1]

    warnings: list[str] = []
    if duplicate_hash_groups:
        warnings.append(
            f"{len(duplicate_hash_groups)} group(s) of hits share identical content_hash "
            "(distinct provenance, duplicate content) — not deduplicated."
        )

    return RetrievalDiagnostics(
        duplicate_chunk_ids=[],
        duplicate_content_hashes=duplicate_hash_groups,
        tied_distance_groups=tied_groups,
        warnings=warnings,
    )

"""Orchestrates retrieval: open the existing collection (read-only) -> build the
embedder -> construct :class:`VectorRetriever` -> run a search or a full
evaluation -> write reports.

The only module in this codebase that imports **both**
:mod:`engineering_rag.services.retriever` and :mod:`engineering_rag.databases.chroma`
for the retrieval milestone (mirrors ``pipelines/indexing_pipeline.py``'s role
for indexing). ``api/retrieve_cli.py`` contains zero business logic and only
calls into this module.

Retrieval never creates, rebuilds, or mutates a collection: it always opens
via ``client.get_collection`` (never ``get_or_create_collection``), so a
missing database path or collection is a hard, explicit failure — never a
silently-created empty one.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from engineering_rag.databases.bm25.index import BM25IndexHandle, build_bm25_index, load_bm25_index
from engineering_rag.databases.bm25.models import BM25CorpusRecord, BM25Manifest
from engineering_rag.databases.chroma import get_client
from engineering_rag.pipelines.retrieval_artifacts import RetrievalRunDirectory
from engineering_rag.pipelines.retrieval_config import RetrievalConfig
from engineering_rag.services.embedder import EmbeddingService
from engineering_rag.services.reranker import RerankCandidate, RerankerConfig
from engineering_rag.services.reranker.cross_encoder import CrossEncoderReranker
from engineering_rag.services.reranker.interface import Reranker
from engineering_rag.services.retriever import (
    CollectionNotFoundError,
    FilterValue,
    RetrievalEvaluationSummary,
    RetrievalRequest,
    RetrievalResponse,
    VectorRetriever,
    check_corpus_compatibility,
    reciprocal_rank_fusion,
    require_compatible,
)
from engineering_rag.services.retriever.bm25_retriever import BM25Retriever
from engineering_rag.services.retriever.evaluation import (
    dataset_hash,
    load_evaluation_dataset,
    run_evaluation,
)

__all__ = [
    "HybridRetriever",
    "InspectionReport",
    "ValidationReport",
    "build_bm25_index_pipeline",
    "build_embedder",
    "build_reranker",
    "inspect_collection",
    "open_collection_readonly",
    "resolve_mode_name",
    "run_evaluation_pipeline",
    "run_hybrid_search",
    "run_search",
    "validate_environment",
]

logger = logging.getLogger(__name__)


def open_collection_readonly(
    config: RetrievalConfig, *, collection_name: str | None = None
) -> tuple[Any, Any]:
    """Open the configured Chroma client + collection without creating anything.

    Raises:
        CollectionNotFoundError: the persistence path has no such collection
            (including the case where the path itself does not exist yet).
    """
    name = collection_name or config.chroma.collection_name
    client = get_client(config.chroma.persistence_path, telemetry=config.chroma.telemetry)
    existing_names = {c.name for c in client.list_collections()}
    if name not in existing_names:
        raise CollectionNotFoundError(
            f"No collection {name!r} at {config.chroma.persistence_path}. "
            f"Available collections: {sorted(existing_names) or '(none)'}. "
            "Retrieval never creates a collection — run engrag-index build first."
        )
    return client, client.get_collection(name=name)


def build_embedder(config: RetrievalConfig, embedder: EmbeddingService | None = None) -> EmbeddingService:
    """Return the injected embedder, or construct the production BGE embedder from ``config.embedding``."""
    if embedder is not None:
        return embedder
    from engineering_rag.services.embedder.bge import BGEEmbeddingService

    return BGEEmbeddingService(config.embedding)


def _build_retriever(config: RetrievalConfig, collection: Any, embedder: EmbeddingService) -> VectorRetriever:
    distance_metric = str((collection.metadata or {}).get("distance_metric", ""))
    return VectorRetriever(
        embedder=embedder,
        collection=collection,
        config=config.search,
        collection_distance_metric=distance_metric,
    )


def run_search(
    query: str,
    config: RetrievalConfig,
    *,
    top_k: int | None = None,
    metadata_filters: dict[str, FilterValue] | None = None,
    collection_name: str | None = None,
    embedder: EmbeddingService | None = None,
) -> RetrievalResponse:
    """Embed ``query`` and search the configured (already-indexed) collection.

    Raises:
        CollectionNotFoundError: the target database/collection does not exist.
        RetrievalError, InvalidFilterError, EmptyCollectionError,
            MalformedChromaResponseError: see ``services/retriever/errors.py``.
    """
    _client, collection = open_collection_readonly(config, collection_name=collection_name)
    resolved_embedder = build_embedder(config, embedder)
    retriever = _build_retriever(config, collection, resolved_embedder)
    request = RetrievalRequest(
        query=query,
        top_k=top_k or config.search.default_top_k,
        metadata_filters=metadata_filters or {},
    )
    return retriever.search(request)


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


def resolve_mode_name(
    *, bm25_enabled: bool, reranker_enabled: bool
) -> Literal["vector", "hybrid", "hybrid-rerank", "vector-rerank"]:
    """Map the two independent toggles onto one of the four named, documented modes."""
    if bm25_enabled and reranker_enabled:
        return "hybrid-rerank"
    if bm25_enabled:
        return "hybrid"
    if reranker_enabled:
        return "vector-rerank"
    return "vector"


def read_chroma_corpus_as_bm25_records(collection: Any) -> list[BM25CorpusRecord]:
    """Read-only: every chunk currently in ``collection``, shaped for the BM25 index.

    The BM25 index is built directly from this read (never from a separate
    ``chunks.jsonl`` path) so "vector and BM25 search the exact same chunks"
    holds by construction, not by a second reconciliation step.
    """
    count = collection.count()
    got = (
        collection.get(include=["documents", "metadatas"])
        if count
        else {"ids": [], "documents": [], "metadatas": []}
    )
    ids = got.get("ids") or []
    documents = got.get("documents") or []
    metadatas = got.get("metadatas") or []
    records: list[BM25CorpusRecord] = []
    for cid, doc, meta in zip(ids, documents, metadatas, strict=True):
        meta = meta or {}
        records.append(
            BM25CorpusRecord(
                chunk_id=cid,
                retrieval_text=doc or "",
                document_id=meta.get("document_id"),
                source_filename=meta.get("source_filename"),
                source_sha256=meta.get("source_sha256"),
                page_numbers=[int(p) for p in _decode_list_field(meta.get("page_numbers"))],
                heading_path=[str(h) for h in _decode_list_field(meta.get("heading_path"))],
                section_title=meta.get("section_title"),
                content_type=meta.get("content_type"),
                content_hash=meta.get("content_hash"),
                chunk_schema_version=meta.get("chunk_schema_version"),
                metadata=meta,
            )
        )
    return records


def build_bm25_index_pipeline(
    config: RetrievalConfig, *, collection_name: str | None = None, force: bool = False
) -> BM25Manifest:
    """Deliberate, explicit BM25 build command (``engrag-retrieve build-bm25``).

    Never runs implicitly from a search — reads the live Chroma collection
    read-only and writes the persistent BM25 index atomically.

    Raises:
        CollectionNotFoundError: the source Chroma collection does not exist.
        CorpusValidationError: duplicate chunk ids or missing/empty text.
    """
    _client, collection = open_collection_readonly(config, collection_name=collection_name)
    records = read_chroma_corpus_as_bm25_records(collection)
    return build_bm25_index(
        records,
        config.bm25,
        collection_name=collection.name,
        chroma_persistence_path=str(config.chroma.persistence_path),
        force=force,
    )


def _chroma_corpus_identity(collection: Any) -> dict[str, Any]:
    got = collection.get(include=["metadatas"])
    ids = got.get("ids") or []
    metadatas = got.get("metadatas") or []
    document_ids = [str(m.get("document_id")) for m in metadatas if m and m.get("document_id")]
    filenames = [str(m.get("source_filename")) for m in metadatas if m and m.get("source_filename")]
    schema_versions = [
        str(m.get("chunk_schema_version")) for m in metadatas if m and m.get("chunk_schema_version")
    ]
    content_hashes = {
        cid: str(m.get("content_hash"))
        for cid, m in zip(ids, metadatas, strict=True)
        if m and m.get("content_hash")
    }
    return {
        "ids": list(ids),
        "document_ids": document_ids,
        "source_filenames": filenames,
        "schema_versions": schema_versions,
        "content_hashes": content_hashes,
    }


def build_reranker(config: RerankerConfig) -> Reranker:
    """Construct the production cross-encoder. Only ever called when reranking is enabled."""
    return CrossEncoderReranker(config)


class HybridRetriever:
    """Orchestrates vector, optional BM25 + RRF fusion, and optional cross-encoder reranking.

    Implements :class:`~engineering_rag.services.retriever.retriever.SearchableRetriever`
    (``search(request) -> RetrievalResponse``), so it is a drop-in replacement
    for :class:`VectorRetriever` everywhere a single-mode caller only needs
    the vector path — including ``services/retriever/evaluation/runner.py``,
    which never branches on which mode is active.

    Expensive resources (the BM25 index, the cross-encoder model) are loaded
    at most once, in ``__init__``, and only when that stage is enabled — never
    per query, and never for a mode that does not use them.
    """

    def __init__(
        self,
        *,
        vector_retriever: VectorRetriever,
        config: RetrievalConfig,
        collection: Any,
        bm25_enabled: bool,
        reranker_enabled: bool,
        vector_top_k: int | None = None,
        bm25_top_k: int | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self._vector_retriever = vector_retriever
        self._config = config
        self._collection = collection
        self._bm25_enabled = bm25_enabled
        self._reranker_enabled = reranker_enabled
        self._vector_top_k = vector_top_k or config.retrieval.vector_top_k
        self._bm25_top_k = bm25_top_k or config.retrieval.bm25_top_k
        self.mode = resolve_mode_name(bm25_enabled=bm25_enabled, reranker_enabled=reranker_enabled)

        self._bm25_index: BM25IndexHandle | None = None
        if bm25_enabled:
            self._bm25_index = load_bm25_index(config.bm25)
            identity = _chroma_corpus_identity(collection)
            report = check_corpus_compatibility(
                collection_name=collection.name,
                chroma_ids=identity["ids"],
                chroma_document_ids=identity["document_ids"],
                chroma_source_filenames=identity["source_filenames"],
                chroma_content_hashes=identity["content_hashes"],
                chroma_schema_versions=identity["schema_versions"],
                bm25_manifest=self._bm25_index.manifest,
            )
            require_compatible(report)

        self._reranker: Reranker | None = None
        if reranker_enabled:
            self._reranker = reranker or build_reranker(config.reranker)

    def search(self, request: RetrievalRequest) -> RetrievalResponse:
        candidate_counts: dict[str, int] = {}
        stage_latencies: dict[str, float] = {}
        warnings: list[str] = []

        vector_request_top_k = (
            self._vector_top_k if (self._bm25_enabled or self._reranker_enabled) else request.top_k
        )
        vector_request = request.model_copy(update={"top_k": vector_request_top_k})
        vector_response = self._vector_retriever.search(vector_request)
        candidate_counts["vector"] = len(vector_response.hits)
        stage_latencies["vector"] = vector_response.total_duration_s
        warnings.extend(vector_response.warnings)

        working_hits = vector_response.hits
        bm25_index_path: str | None = None
        bm25_fingerprint: str | None = None

        if self._bm25_enabled:
            assert self._bm25_index is not None  # noqa: S101 - set in __init__ whenever bm25_enabled
            bm25_index_path = self._config.bm25.index_path
            bm25_fingerprint = self._bm25_index.manifest.corpus_fingerprint
            bm25_retriever = BM25Retriever(index=self._bm25_index, config=self._config.search)
            bm25_outcome = bm25_retriever.search(
                request.query, top_k=self._bm25_top_k, metadata_filters=request.metadata_filters
            )
            candidate_counts["bm25"] = len(bm25_outcome.hits)
            stage_latencies["bm25"] = round(bm25_outcome.duration_s, 6)

            fusion_started = time.perf_counter()
            fused = reciprocal_rank_fusion(
                vector_response.hits, bm25_outcome.hits, rrf_k=self._config.fusion.rrf_k
            )
            stage_latencies["fusion"] = round(time.perf_counter() - fusion_started, 6)
            candidate_counts["fused"] = len(fused)
            working_hits = [f.hit for f in fused]

        if self._reranker_enabled:
            assert self._reranker is not None  # noqa: S101 - set in __init__ whenever reranker_enabled
            rr_config = self._config.reranker
            pool = working_hits[: rr_config.candidate_top_k]
            candidates = [RerankCandidate(chunk_id=h.chunk_id, text=h.retrieval_text) for h in pool]
            rerank_started = time.perf_counter()
            results = self._reranker.rerank(request.query, candidates)
            stage_latencies["reranker"] = round(time.perf_counter() - rerank_started, 6)
            candidate_counts["reranked"] = len(results)

            by_id = {h.chunk_id: h for h in pool}
            final_hits = []
            for result in results[: request.top_k]:
                hit = by_id[result.chunk_id]
                final_hits.append(
                    hit.model_copy(update={"reranker_rank": result.rank, "reranker_score": result.score})
                )
        else:
            final_hits = list(working_hits[: request.top_k])

        final_hits = [
            hit.model_copy(update={"rank": i, "final_rank": i}) for i, hit in enumerate(final_hits, start=1)
        ]

        total_duration = sum(stage_latencies.values())
        return vector_response.model_copy(
            update={
                "hits": final_hits,
                "returned_count": len(final_hits),
                "requested_top_k": request.top_k,
                "retrieval_mode": self.mode,
                "vector_enabled": True,
                "bm25_enabled": self._bm25_enabled,
                "reranker_enabled": self._reranker_enabled,
                "candidate_counts": candidate_counts,
                "stage_latencies_s": stage_latencies,
                "bm25_index_path": bm25_index_path,
                "bm25_corpus_fingerprint": bm25_fingerprint,
                "reranker_model": self._config.reranker.model_name if self._reranker_enabled else None,
                "reranker_model_revision": self._config.reranker.model_revision
                if self._reranker_enabled
                else None,
                "warnings": warnings,
                "total_duration_s": round(total_duration, 6),
            }
        )


def run_hybrid_search(
    query: str,
    config: RetrievalConfig,
    *,
    top_k: int | None = None,
    bm25_enabled: bool | None = None,
    reranker_enabled: bool | None = None,
    metadata_filters: dict[str, FilterValue] | None = None,
    collection_name: str | None = None,
    embedder: EmbeddingService | None = None,
    reranker: Reranker | None = None,
) -> RetrievalResponse:
    """Build one :class:`HybridRetriever` and run a single search through it.

    Convenience wrapper for the CLI's ``search`` command; ``evaluate`` builds
    and reuses one ``HybridRetriever`` across every case instead of calling
    this per-query, so the BM25 index and reranker model load only once.

    Raises:
        CollectionNotFoundError: the target collection does not exist.
        BM25IndexNotFoundError: BM25 is enabled but no index has been built.
        CorpusCompatibilityError: BM25 is enabled but its index does not
            match the live Chroma collection.
        RetrievalError, InvalidFilterError, EmptyCollectionError: see
            ``services/retriever/errors.py``.
    """
    _client, collection = open_collection_readonly(config, collection_name=collection_name)
    resolved_embedder = build_embedder(config, embedder)
    vector_retriever = _build_retriever(config, collection, resolved_embedder)

    resolved_bm25 = config.retrieval.bm25_enabled if bm25_enabled is None else bm25_enabled
    resolved_reranker = config.reranker.enabled if reranker_enabled is None else reranker_enabled

    hybrid = HybridRetriever(
        vector_retriever=vector_retriever,
        config=config,
        collection=collection,
        bm25_enabled=resolved_bm25,
        reranker_enabled=resolved_reranker,
        reranker=reranker,
    )
    request = RetrievalRequest(
        query=query,
        top_k=top_k or config.retrieval.final_top_k,
        metadata_filters=metadata_filters or {},
    )
    return hybrid.search(request)


class InspectionReport:
    """Structured, JSON-serializable result of ``engrag-retrieve inspect``."""

    def __init__(
        self,
        *,
        chroma_path: str,
        collection_name: str,
        exists: bool,
        count: int,
        distance_metric: str,
        embedding_dimension: int | None,
        sample_metadata_keys: list[str],
        identity_metadata: dict[str, Any],
        source_filename_distribution: dict[str, int],
    ) -> None:
        self.chroma_path = chroma_path
        self.collection_name = collection_name
        self.exists = exists
        self.count = count
        self.distance_metric = distance_metric
        self.embedding_dimension = embedding_dimension
        self.sample_metadata_keys = sample_metadata_keys
        self.identity_metadata = identity_metadata
        self.source_filename_distribution = source_filename_distribution

    def as_dict(self) -> dict[str, Any]:
        return {
            "chroma_path": self.chroma_path,
            "collection_name": self.collection_name,
            "exists": self.exists,
            "count": self.count,
            "distance_metric": self.distance_metric,
            "embedding_dimension": self.embedding_dimension,
            "sample_metadata_keys": self.sample_metadata_keys,
            "identity_metadata": self.identity_metadata,
            "source_filename_distribution": self.source_filename_distribution,
        }


def inspect_collection(config: RetrievalConfig, *, collection_name: str | None = None) -> InspectionReport:
    """Non-mutating inspection of the configured collection. Never creates anything."""
    name = collection_name or config.chroma.collection_name
    try:
        _client, collection = open_collection_readonly(config, collection_name=name)
    except CollectionNotFoundError:
        return InspectionReport(
            chroma_path=str(config.chroma.persistence_path),
            collection_name=name,
            exists=False,
            count=0,
            distance_metric="",
            embedding_dimension=None,
            sample_metadata_keys=[],
            identity_metadata={},
            source_filename_distribution={},
        )

    identity = dict(collection.metadata or {})
    count = collection.count()
    sample = collection.get(limit=min(5, count), include=["metadatas"]) if count else {"metadatas": []}
    sample_keys = sorted({k for m in (sample.get("metadatas") or []) for k in (m or {})})

    distribution: dict[str, int] = {}
    if count:
        all_meta = collection.get(include=["metadatas"]).get("metadatas") or []
        for m in all_meta:
            filename = (m or {}).get("source_filename", "unknown")
            distribution[filename] = distribution.get(filename, 0) + 1

    return InspectionReport(
        chroma_path=str(config.chroma.persistence_path),
        collection_name=name,
        exists=True,
        count=count,
        distance_metric=str(identity.get("distance_metric", "")),
        embedding_dimension=identity.get("embedding_dimension"),
        sample_metadata_keys=sample_keys,
        identity_metadata=identity,
        source_filename_distribution=distribution,
    )


class ValidationReport:
    """Non-destructive database/compatibility checks — result of ``engrag-retrieve validate``."""

    def __init__(self, *, checks: list[dict[str, Any]]) -> None:
        self.checks = checks

    @property
    def passed(self) -> bool:
        return all(c["passed"] for c in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {"status": "PASS" if self.passed else "FAIL", "checks": self.checks}


def validate_environment(config: RetrievalConfig, *, collection_name: str | None = None) -> ValidationReport:
    """Run every non-destructive compatibility check without embedding a query or writing anything."""
    checks: list[dict[str, Any]] = []
    name = collection_name or config.chroma.collection_name

    persistence_path = Path(config.chroma.persistence_path)
    path_exists = persistence_path.is_dir()
    checks.append(
        {
            "check_id": "chroma_path_exists",
            "passed": path_exists,
            "summary": f"{persistence_path} {'exists' if path_exists else 'does not exist'}",
        }
    )
    if not path_exists:
        return ValidationReport(checks=checks)

    try:
        _client, collection = open_collection_readonly(config, collection_name=name)
    except CollectionNotFoundError as exc:
        checks.append({"check_id": "collection_exists", "passed": False, "summary": str(exc)})
        return ValidationReport(checks=checks)
    checks.append({"check_id": "collection_exists", "passed": True, "summary": f"collection {name!r} found"})

    count = collection.count()
    checks.append(
        {
            "check_id": "collection_not_empty",
            "passed": count > 0,
            "summary": f"collection count = {count}",
        }
    )

    identity = dict(collection.metadata or {})
    stored_dim = identity.get("embedding_dimension")
    dim_ok = stored_dim == config.embedding.expected_dimension
    checks.append(
        {
            "check_id": "embedding_dimension_matches_profile",
            "passed": dim_ok,
            "summary": f"stored={stored_dim!r}, profile expects={config.embedding.expected_dimension}",
        }
    )

    stored_metric = str(identity.get("distance_metric", ""))
    metric_ok = stored_metric == "cosine" == config.chroma.distance_metric
    checks.append(
        {
            "check_id": "distance_metric_is_cosine",
            "passed": metric_ok,
            "summary": f"stored={stored_metric!r}",
        }
    )

    stored_model = str(identity.get("model_name", ""))
    model_ok = stored_model == config.embedding.model_name
    checks.append(
        {
            "check_id": "model_name_matches_profile",
            "passed": model_ok,
            "summary": f"stored={stored_model!r}, profile={config.embedding.model_name!r}",
        }
    )

    return ValidationReport(checks=checks)


def _versions() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version

    versions: dict[str, str] = {}
    for dist in ("sentence-transformers", "chromadb", "numpy"):
        try:
            versions[dist] = version(dist)
        except PackageNotFoundError:
            versions[dist] = "not-installed"
    return versions


def run_evaluation_pipeline(
    config: RetrievalConfig,
    *,
    embedder: EmbeddingService | None = None,
    collection_name: str | None = None,
    reproduction_command: str = "engrag-retrieve evaluate",
    bm25_enabled: bool | None = None,
    reranker_enabled: bool | None = None,
    reranker: Reranker | None = None,
) -> tuple[RetrievalRunDirectory, list[dict[str, Any]], RetrievalEvaluationSummary]:
    """Run the full ground-truth benchmark and write every report under a unique run directory.

    Builds one :class:`HybridRetriever` (loading the BM25 index and/or the
    cross-encoder at most once, only if that stage is enabled) and reuses it
    across every case, so a hybrid or hybrid-rerank evaluation run never
    reloads either resource per query.

    Raises:
        FileNotFoundError: the evaluation dataset does not exist.
        ValueError: the dataset is empty or malformed.
        CollectionNotFoundError: the target collection does not exist.
        BM25IndexNotFoundError: BM25 is enabled but no index has been built.
        CorpusCompatibilityError: BM25 is enabled but its index does not
            match the live Chroma collection.
    """
    started = time.perf_counter()
    dataset_path = Path(config.evaluation.dataset_path)
    cases = load_evaluation_dataset(dataset_path)
    d_hash = dataset_hash(dataset_path)

    _client, collection = open_collection_readonly(config, collection_name=collection_name)
    resolved_embedder = build_embedder(config, embedder)
    vector_retriever = _build_retriever(config, collection, resolved_embedder)
    model_info = resolved_embedder.model_info()

    resolved_bm25 = config.retrieval.bm25_enabled if bm25_enabled is None else bm25_enabled
    resolved_reranker = config.reranker.enabled if reranker_enabled is None else reranker_enabled
    hybrid = HybridRetriever(
        vector_retriever=vector_retriever,
        config=config,
        collection=collection,
        bm25_enabled=resolved_bm25,
        reranker_enabled=resolved_reranker,
        reranker=reranker,
    )

    run = RetrievalRunDirectory.create(Path(config.evaluation.output_root))

    validation = validate_environment(config, collection_name=collection_name)
    run.write_json_atomic("validation_report.json", validation.as_dict())

    results, summary = run_evaluation(
        hybrid,
        cases,
        run_id=run.root.name,
        dataset_path=str(dataset_path),
        dataset_version=str(len(cases)),
        dataset_hash=d_hash,
        k_values=config.evaluation.k_values,
        unanswerable_similarity_threshold=config.evaluation.unanswerable_similarity_threshold,
        collection_name=collection.name,
        collection_count=collection.count(),
        distance_metric=str((collection.metadata or {}).get("distance_metric", "")),
        embedding_model=model_info.model_name,
        embedding_revision=model_info.resolved_revision,
        reproduction_command=reproduction_command,
        retrieval_mode=hybrid.mode,
        bm25_enabled=resolved_bm25,
        reranker_enabled=resolved_reranker,
    )

    result_rows = [r.model_dump(mode="json") for r in results]
    run.write_jsonl_atomic("retrieval_results.jsonl", result_rows)
    run.write_json_atomic(
        "retrieval_evaluation_report.json",
        {"summary": summary.model_dump(mode="json"), "per_case": result_rows},
    )
    run.write_text_atomic("retrieval_evaluation_summary.md", _render_summary_md(summary))
    run.write_json_atomic(
        "retrieval_manifest.json",
        {
            "run_id": run.root.name,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "config_hash": config.config_hash(),
            "config": config.effective_dict(),
            "versions": _versions(),
            "collection_name": collection.name,
            "collection_count": collection.count(),
            "retrieval_mode": hybrid.mode,
            "bm25_enabled": resolved_bm25,
            "reranker_enabled": resolved_reranker,
            "duration_s": round(time.perf_counter() - started, 3),
            "reproduction_command": reproduction_command,
        },
    )
    logger.info(
        "Evaluation complete: %s (%d case(s)), report at %s",
        run.root.name,
        summary.case_count,
        run.root,
    )
    return run, result_rows, summary


def _render_summary_md(summary: RetrievalEvaluationSummary) -> str:
    lines = [
        f"# Retrieval Evaluation Summary — {summary.run_id}",
        "",
        f"- Mode: `{summary.retrieval_mode}` (bm25_enabled={summary.bm25_enabled}, "
        f"reranker_enabled={summary.reranker_enabled})",
        "",
        f"- Dataset: `{summary.dataset_path}` ({summary.case_count} case(s), hash `{summary.dataset_hash[:12]}`)",
        f"- Positive cases: {summary.positive_case_count}  |  Negative/unanswerable: {summary.negative_case_count}",
        f"- Human-reviewed: {summary.human_reviewed_count}/{summary.case_count} "
        f"(approved: {summary.human_approved_count})",
        f"- Collection: `{summary.collection_name}` ({summary.collection_count} records, "
        f"{summary.distance_metric} distance)",
        f"- Model: {summary.embedding_model} (revision={summary.embedding_revision or 'unknown'})",
        "",
        "## Metrics",
        "",
        "| K | Hit Rate | Recall | Precision | nDCG |",
        "|---|---|---|---|---|",
    ]
    for k in summary.k_values:
        lines.append(
            f"| {k} | {summary.hit_rate_at_k.get(k, 0.0):.3f} | {summary.recall_at_k.get(k, 0.0):.3f} | "
            f"{summary.precision_at_k.get(k, 0.0):.3f} | {summary.ndcg_at_k.get(k, 0.0):.3f} |"
        )
    lines += [
        "",
        f"- Mean Reciprocal Rank: {summary.mean_reciprocal_rank:.3f}",
        f"- No-result accuracy (heuristic, unanswerable cases): "
        f"{'n/a' if summary.no_result_accuracy is None else f'{summary.no_result_accuracy:.3f}'}",
        "",
        "## Latency",
        "",
        f"- p50: {summary.latency_p50_s * 1000:.1f} ms  |  p95: {summary.latency_p95_s * 1000:.1f} ms  |  "
        f"mean: {summary.latency_mean_s * 1000:.1f} ms",
        "",
        "## Limitations",
        "",
    ]
    lines += [f"- {item}" for item in summary.limitations]
    if summary.failures:
        lines += ["", "## Failures", ""]
        lines += [f"- {item}" for item in summary.failures]
    lines += [
        "",
        "## Reproduction",
        "",
        "```",
        summary.reproduction_command,
        "```",
    ]
    return "\n".join(lines) + "\n"

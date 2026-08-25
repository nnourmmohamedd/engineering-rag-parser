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

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engineering_rag.databases.chroma import get_client
from engineering_rag.pipelines.retrieval_artifacts import RetrievalRunDirectory
from engineering_rag.pipelines.retrieval_config import RetrievalConfig
from engineering_rag.services.embedder import EmbeddingService
from engineering_rag.services.retriever import (
    CollectionNotFoundError,
    RetrievalEvaluationSummary,
    RetrievalRequest,
    RetrievalResponse,
    VectorRetriever,
)
from engineering_rag.services.retriever.evaluation import (
    dataset_hash,
    load_evaluation_dataset,
    run_evaluation,
)

__all__ = [
    "InspectionReport",
    "ValidationReport",
    "build_embedder",
    "inspect_collection",
    "open_collection_readonly",
    "run_evaluation_pipeline",
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
    metadata_filters: dict[str, str | int | float | bool] | None = None,
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
) -> tuple[RetrievalRunDirectory, list[dict[str, Any]], RetrievalEvaluationSummary]:
    """Run the full ground-truth benchmark and write every report under a unique run directory.

    Raises:
        FileNotFoundError: the evaluation dataset does not exist.
        ValueError: the dataset is empty or malformed.
        CollectionNotFoundError: the target collection does not exist.
    """
    started = time.perf_counter()
    dataset_path = Path(config.evaluation.dataset_path)
    cases = load_evaluation_dataset(dataset_path)
    d_hash = dataset_hash(dataset_path)

    _client, collection = open_collection_readonly(config, collection_name=collection_name)
    resolved_embedder = build_embedder(config, embedder)
    retriever = _build_retriever(config, collection, resolved_embedder)
    model_info = resolved_embedder.model_info()

    run = RetrievalRunDirectory.create(Path(config.evaluation.output_root))

    validation = validate_environment(config, collection_name=collection_name)
    run.write_json_atomic("validation_report.json", validation.as_dict())

    results, summary = run_evaluation(
        retriever,
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

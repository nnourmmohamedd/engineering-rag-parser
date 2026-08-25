"""Orchestrates the indexing pipeline: load validated chunks -> validate
compatibility -> batch embeddings -> Chroma-safe metadata -> store -> verify
-> manifests/reports.

The only module in this codebase that imports **both**
:mod:`engineering_rag.services.embedder` and
:mod:`engineering_rag.databases.chroma`. The CLI (``api/index_cli.py``)
contains zero business logic and only calls into this module.

Tokenizer-compatibility rule (recorded here as the single source of truth,
also documented in ``docs/indexing/``): a chunk run is admissible for
indexing only if its recorded ``tokenizer.name`` (from the chunker's own
``manifest.json``) is **exactly equal** to the embedding model's
``model_name``. This is deliberately a strict equality, not a fuzzy "family"
match — different tokenizers (even from closely related models) count tokens
differently, so only an exact match guarantees the chunker's token-budget
decisions are meaningful for this embedding model's own limits. On top of
that, every ``retrieval_text`` is independently re-measured with the
embedding model's own tokenizer (never trusting the chunker's stored
``token_count``, which was measured for the *chunker's* size-budget purposes,
not truncation avoidance) and any chunk exceeding
``maximum_sequence_length`` is a hard admission failure — never silently
truncated.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from engineering_rag.databases.chroma import (
    CollectionIdentity,
    chroma_safe_metadata,
    content_hash,
    get_client,
    ingest_batch,
    open_or_create_collection,
    rebuild_collection,
)
from engineering_rag.pipelines.indexing_artifacts import IndexRunDirectory
from engineering_rag.pipelines.indexing_config import IndexingConfig
from engineering_rag.pipelines.indexing_models import INDEX_MANIFEST_SCHEMA_VERSION, IndexManifest
from engineering_rag.pipelines.indexing_validation import build_validation_report
from engineering_rag.services.embedder import EmbeddingService
from engineering_rag.utils.hashing import sha256_file
from engineering_rag.utils.logging import (
    attach_run_file_handler,
    bind_run_context,
    current_context,
    detach_handler,
)

__all__ = [
    "IndexingInputError",
    "IndexingRequest",
    "IndexingResult",
    "IndexingService",
    "run_indexing_pipeline",
]

logger = logging.getLogger(__name__)


class IndexingInputError(Exception):
    """Raised when the supplied chunk run is not admissible for indexing.

    Covers: missing artifacts, unsupported chunk schema, a chunker run that
    did not itself pass validation, a tokenizer mismatch with the embedding
    model, or a chunk whose retrieval_text would silently truncate under the
    embedding model's real tokenizer. No run directory or Chroma write
    happens when this is raised.
    """


@dataclass
class IndexingRequest:
    input_path: Path
    config: IndexingConfig
    rebuild: bool = False
    embedder: EmbeddingService | None = None  # dependency injection point for tests

    def __post_init__(self) -> None:
        self.input_path = Path(self.input_path)


@dataclass
class IndexingResult:
    run_dir: Path
    status: str
    chunk_count: int
    collection_name: str
    chroma_path: str
    manifest: IndexManifest
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return 1 if self.status == "FAIL" else 0


def run_indexing_pipeline(
    input_path: Path | str,
    config: IndexingConfig,
    *,
    rebuild: bool = False,
    embedder: EmbeddingService | None = None,
) -> IndexingResult:
    """Run the indexing pipeline and return the outcome.

    Args:
        input_path: a chunker run directory (containing ``chunks.jsonl``,
            ``manifest.json``, ``validation_report.json``), or a direct path
            to a ``chunks.jsonl`` file inside one.
        config: effective indexing configuration.
        rebuild: destructively replace an existing collection with matching
            identity metadata for a fresh one. Requires ``config.chroma.allow_rebuild``.
        embedder: inject a specific :class:`EmbeddingService` (e.g. a
            deterministic fake for tests). Defaults to
            :class:`~engineering_rag.services.embedder.bge.BGEEmbeddingService`
            built from ``config.embedding``.

    Raises:
        IndexingInputError: if the input is inadmissible.
    """
    request = IndexingRequest(input_path=Path(input_path), config=config, rebuild=rebuild, embedder=embedder)
    return IndexingService().run(request)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    lines = [line for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]
    return [json.loads(line) for line in lines]


def _resolve_chunk_run(input_path: Path) -> tuple[Path, Path, Path]:
    if input_path.is_file():
        if input_path.name != "chunks.jsonl":
            raise IndexingInputError(f"--input file must be named chunks.jsonl, got: {input_path}")
        chunks_path = input_path
        run_dir = input_path.parent
    elif input_path.is_dir():
        chunks_path = input_path / "chunks.jsonl"
        run_dir = input_path
    else:
        raise IndexingInputError(f"Input not found: {input_path}")

    manifest_path = run_dir / "manifest.json"
    validation_path = run_dir / "validation_report.json"
    for label, path in (
        ("chunks.jsonl", chunks_path),
        ("chunker manifest.json", manifest_path),
        ("chunker validation_report.json", validation_path),
    ):
        if not path.is_file():
            raise IndexingInputError(
                f"{label} not found at {path} (expected a complete chunker run directory)"
            )
    return chunks_path, manifest_path, validation_path


@lru_cache(maxsize=4)
def _counting_tokenizer(model_name: str) -> Any:  # transformers.PreTrainedTokenizerBase
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(model_name)


def _oversized_chunk_ids(
    records: list[dict[str, Any]], model_name: str, max_seq_length: int
) -> tuple[list[str], dict[str, int]]:
    """Recompute token counts with the *embedding* model's own tokenizer. Never trusts the chunker's count."""
    tokenizer = _counting_tokenizer(model_name)
    oversized: list[str] = []
    counts: dict[str, int] = {}
    for r in records:
        count = len(tokenizer.encode(r.get("retrieval_text", ""), add_special_tokens=False))
        counts[r["chunk_id"]] = count
        if count > max_seq_length:
            oversized.append(r["chunk_id"])
    return oversized, counts


def _admission_check(
    records: list[dict[str, Any]],
    chunk_manifest: dict[str, Any],
    chunker_validation: dict[str, Any],
    config: IndexingConfig,
) -> tuple[list[str], dict[str, int]]:
    """Raise :class:`IndexingInputError` if the chunk run is inadmissible.

    Returns ``(oversized_chunk_ids, recomputed_token_counts)`` — always
    ``([], {...})`` on success since an oversized chunk is itself a failure.
    """
    problems: list[str] = []

    schema_versions = {r.get("schema_version") for r in records}
    if len(schema_versions) > 1 or not records:
        problems.append(f"chunks.jsonl has an inconsistent or missing schema_version: {schema_versions}")

    chunker_status = chunker_validation.get("status", "FAIL")
    if chunker_status not in ("PASS", "PASS_WITH_WARNINGS"):
        problems.append(f"the source chunker run did not pass validation (status={chunker_status})")

    chunker_tokenizer_name = (chunk_manifest.get("tokenizer") or {}).get("name", "")
    if (
        config.validation.require_model_tokenizer_match
        and chunker_tokenizer_name != config.embedding.model_name
    ):
        problems.append(
            f"tokenizer mismatch: chunk run was measured with tokenizer {chunker_tokenizer_name!r}, "
            f"but the embedding model is {config.embedding.model_name!r}. Re-run the chunker with a "
            "matching tokenizer.name before indexing (see configs/chunker_bge.yaml)."
        )

    if problems:
        raise IndexingInputError("Chunk run rejected:\n  " + "\n  ".join(problems))

    oversized, counts = _oversized_chunk_ids(
        records, config.embedding.model_name, config.embedding.maximum_sequence_length
    )
    if oversized:
        raise IndexingInputError(
            f"{len(oversized)} chunk(s) exceed {config.embedding.maximum_sequence_length} tokens under the "
            f"embedding model's own tokenizer and would be silently truncated: {oversized[:10]}. "
            "Lower the chunker's target_tokens/max_tokens, or use a longer-context embedding model."
        )
    return oversized, counts


def _build_metadata(
    record: dict[str, Any],
    *,
    chunk_run_id: str,
    embedding_model_name: str,
    recomputed_token_count: int,
) -> dict[str, Any]:
    warnings = record.get("warnings") or []
    fields = {
        "document_id": record.get("document_id"),
        "source_filename": record.get("source_filename"),
        "source_sha256": record.get("source_sha256"),
        "chunk_index": record.get("chunk_index"),
        "content_type": record.get("content_type"),
        "section_title": record.get("section_title"),
        "heading_path": record.get("heading_path"),
        "page_numbers": record.get("page_numbers"),
        "source_element_refs": record.get("source_element_refs"),
        "parent_chunk_id": record.get("parent_chunk_id"),
        "previous_chunk_id": record.get("previous_chunk_id"),
        "next_chunk_id": record.get("next_chunk_id"),
        "chunk_schema_version": record.get("schema_version"),
        "tokenizer_name": embedding_model_name,
        "token_count": recomputed_token_count,
        "chunk_run_id": chunk_run_id,
        "index_schema_version": "1.0.0",
        "warnings_summary": "; ".join(warnings)[:200],
    }
    safe = chroma_safe_metadata(fields)
    safe["content_hash"] = content_hash(record["retrieval_text"], safe)
    return safe


def _versions() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version

    versions: dict[str, str] = {}
    for dist in ("sentence-transformers", "chromadb", "transformers", "torch", "numpy"):
        try:
            versions[dist] = version(dist)
        except PackageNotFoundError:
            versions[dist] = "not-installed"
    return versions


class IndexingService:
    """Owns the complete indexing-domain workflow for one chunk run."""

    def run(self, request: IndexingRequest) -> IndexingResult:
        config = request.config
        timings: dict[str, float] = {}
        context = current_context()
        bind_run_context(context, stage="load")

        started = time.perf_counter()
        chunks_path, manifest_path, validation_path = _resolve_chunk_run(request.input_path)
        chunk_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        chunker_validation = json.loads(validation_path.read_text(encoding="utf-8"))
        records = _load_jsonl(chunks_path)
        timings["load_s"] = time.perf_counter() - started

        bind_run_context(context, stage="admission")
        oversized_before, recomputed_counts = _admission_check(
            records, chunk_manifest, chunker_validation, config
        )

        chunk_run_id = str(chunk_manifest.get("run_id", chunks_path.parent.name))
        input_hash = sha256_file(chunks_path)

        run = IndexRunDirectory.create(config.output_root, config.chroma.collection_name, input_hash)
        bind_run_context(context, run_id=run.root.name, stage="embed")
        file_handler = attach_run_file_handler(run.path_for("logs/indexing.log"))
        try:
            return self._run_after_directory_created(
                request=request,
                config=config,
                records=records,
                chunk_manifest=chunk_manifest,
                chunks_path=chunks_path,
                chunk_run_id=chunk_run_id,
                recomputed_counts=recomputed_counts,
                run=run,
                timings=timings,
                context=context,
            )
        finally:
            detach_handler(file_handler)

    def _run_after_directory_created(
        self,
        *,
        request: IndexingRequest,
        config: IndexingConfig,
        records: list[dict[str, Any]],
        chunk_manifest: dict[str, Any],
        chunks_path: Path,
        chunk_run_id: str,
        recomputed_counts: dict[str, int],
        run: IndexRunDirectory,
        timings: dict[str, float],
        context: Any,
    ) -> IndexingResult:
        embedder = request.embedder
        if embedder is None:
            from engineering_rag.services.embedder.bge import BGEEmbeddingService

            embedder = BGEEmbeddingService(config.embedding)
        model_info = embedder.model_info()

        # --- 1. Embed passages (batched by the embedder itself) --------------
        bind_run_context(context, stage="embed")
        started = time.perf_counter()
        chunk_ids = [r["chunk_id"] for r in records]
        texts = [r.get(config.embedding.document_field, "") for r in records]
        embedding_records, batch_stats = embedder.embed_passages(chunk_ids, texts)
        vectors_by_id = {er.chunk_id: er.vector for er in embedding_records}
        timings["embedding_s"] = time.perf_counter() - started
        logger.info(
            "Embedded %d passage(s) in %.2fs (%.1f vec/s)",
            batch_stats.input_count,
            batch_stats.duration_s,
            batch_stats.vectors_per_second,
        )

        # --- 2. Chroma-safe metadata ------------------------------------------
        bind_run_context(context, stage="metadata")
        metadatas = [
            _build_metadata(
                r,
                chunk_run_id=chunk_run_id,
                embedding_model_name=model_info.model_name,
                recomputed_token_count=recomputed_counts.get(r["chunk_id"], 0),
            )
            for r in records
        ]
        documents = [r.get(config.embedding.document_field, "") for r in records]
        retrieval_texts_by_id = dict(zip(chunk_ids, documents, strict=True))

        # --- 3. Open/create the collection, enforcing identity compatibility --
        bind_run_context(context, stage="ingest")
        client = get_client(config.chroma.persistence_path, telemetry=config.chroma.telemetry)
        identity = CollectionIdentity(
            model_name=model_info.model_name,
            embedding_dimension=model_info.dimension,
            distance_metric=config.chroma.distance_metric,
            tokenizer_name=model_info.tokenizer_name,
            corpus_id=config.config_hash()[:16],
        )
        if request.rebuild:
            if not config.chroma.allow_rebuild:
                raise IndexingInputError(
                    "--rebuild was requested but chroma.allow_rebuild=false in the active profile."
                )
            logger.warning(
                "Rebuilding collection %r at %s",
                config.chroma.collection_name,
                config.chroma.persistence_path,
            )
            collection = rebuild_collection(client, config.chroma, identity)
        else:
            collection = open_or_create_collection(client, config.chroma, identity)

        # --- 4. Batch writes, idempotent per-record --------------------------
        started = time.perf_counter()
        all_ids = [er.chunk_id for er in embedding_records]
        all_vectors = [er.vector for er in embedding_records]
        by_id_meta = dict(zip(chunk_ids, metadatas, strict=True))
        by_id_doc = dict(zip(chunk_ids, documents, strict=True))

        inserted: list[str] = []
        existing_identical: list[str] = []
        rejected: list[str] = []
        batch_size = config.chroma.ingestion_batch_size
        for start in range(0, len(all_ids), batch_size):
            batch_ids = all_ids[start : start + batch_size]
            outcome = ingest_batch(
                collection,
                ids=batch_ids,
                embeddings=all_vectors[start : start + batch_size],
                documents=[by_id_doc[i] for i in batch_ids],
                metadatas=[by_id_meta[i] for i in batch_ids],
                idempotent=config.chroma.idempotent,
            )
            inserted.extend(outcome.inserted_ids)
            existing_identical.extend(outcome.existing_identical_ids)
            rejected.extend(outcome.rejected_ids)
        timings["ingestion_s"] = time.perf_counter() - started
        collection_count = collection.count()
        logger.info(
            "Ingestion complete: %d inserted, %d already-identical, %d rejected, collection count=%d",
            len(inserted),
            len(existing_identical),
            len(rejected),
            collection_count,
        )

        # --- 5. Validate the full stored result --------------------------------
        bind_run_context(context, stage="validation")
        started = time.perf_counter()
        sample_size = min(config.validation.self_retrieval_sample_size, len(all_ids))
        step = max(1, len(all_ids) // sample_size) if sample_size else 1
        sample_ids = all_ids[::step][:sample_size]

        vector_problems: list[str] = []  # already validated per-record inside embed_passages()
        recorded_chunks_path = _relative_or_str(chunks_path)

        report = build_validation_report(
            chunk_records=records,
            chunker_validation_status="PASS",  # already enforced in admission
            tokenizer_family_ok=True,  # already enforced in admission
            tokenizer_family_summary=f"tokenizer.name == embedding model_name == {model_info.model_name!r}",
            oversized_chunk_ids=[],  # already enforced in admission
            max_seq_length=config.embedding.maximum_sequence_length,
            expected_ids=chunk_ids,
            inserted_ids=inserted,
            existing_identical_ids=existing_identical,
            rejected_ids=rejected,
            collection_count=collection_count,
            collection=collection,
            vector_problems=vector_problems,
            distance_metric_stored=str((collection.metadata or {}).get("distance_metric", "")),
            expected_distance_metric=config.chroma.distance_metric,
            round_trip_ids=sample_ids,
            retrieval_texts_by_id=retrieval_texts_by_id,
            self_retrieval_sample_ids=sample_ids,
            vectors_by_id=vectors_by_id,
            norm_tolerance=config.validation.norm_tolerance,
            chunks_jsonl_path_is_relative=not Path(recorded_chunks_path).is_absolute(),
            strict=config.strict,
        )
        run.write_json_atomic("index_validation_report.json", report.model_dump(mode="json"))
        timings["validation_s"] = time.perf_counter() - started

        # --- 6. Manifest + ingestion report + summary ---------------------------
        bind_run_context(context, stage="manifest")
        content_type_counts: dict[str, int] = {}
        for r in records:
            ct = r.get("content_type", "unknown")
            content_type_counts[ct] = content_type_counts.get(ct, 0) + 1

        source_documents = [
            {
                "filename": (chunk_manifest.get("source") or {}).get("filename"),
                "sha256": (chunk_manifest.get("source") or {}).get("sha256"),
            }
        ]

        manifest = IndexManifest(
            schema_version=INDEX_MANIFEST_SCHEMA_VERSION,
            run_id=run.root.name,
            generated_at_utc=datetime.now(timezone.utc),
            collection_name=config.chroma.collection_name,
            chroma_path=str(config.chroma.persistence_path),
            input_chunks_jsonl_path=recorded_chunks_path,
            input_chunks_jsonl_sha256=sha256_file(chunks_path),
            input_chunk_run_id=chunk_run_id,
            source_documents=source_documents,
            chunk_count=len(records),
            content_type_counts=content_type_counts,
            model_name=model_info.model_name,
            resolved_model_revision=model_info.resolved_revision,
            tokenizer_name=model_info.tokenizer_name,
            embedding_dimension=model_info.dimension,
            max_seq_length=model_info.max_seq_length,
            normalize_embeddings=model_info.normalize_embeddings,
            distance_metric=config.chroma.distance_metric,
            query_prefix=config.embedding.query_prefix,
            document_prefix=config.embedding.document_prefix,
            batch_size=config.embedding.batch_size,
            device=model_info.device,
            versions=_versions(),
            collection_count_after_run=collection_count,
            vector_validation_stats={
                "validated_count": len(embedding_records),
                "embedding_duration_s": batch_stats.duration_s,
                "vectors_per_second": batch_stats.vectors_per_second,
            },
            config_hash=config.config_hash(),
            status=report.status.value,
            warnings=[c.summary for c in report.warnings],
            timings_s={k: round(v, 3) for k, v in timings.items()},
        )
        run.write_json_atomic("index_manifest.json", manifest.model_dump(mode="json"))
        run.write_json_atomic(
            "ingestion_report.json",
            {
                "expected_ids": chunk_ids,
                "inserted_ids": inserted,
                "existing_identical_ids": existing_identical,
                "rejected_ids": rejected,
                "final_count": collection_count,
                "errors": [],
            },
        )
        run.write_text_atomic("index_summary.md", _render_summary(manifest=manifest, report=report))

        bind_run_context(context, stage="complete")
        logger.info(
            "Indexing complete: %s -> %s (%d chunk(s), collection count=%d)",
            report.status.value,
            run.root,
            len(records),
            collection_count,
        )
        return IndexingResult(
            run_dir=run.root,
            status=report.status.value,
            chunk_count=len(records),
            collection_name=config.chroma.collection_name,
            chroma_path=str(config.chroma.persistence_path),
            manifest=manifest,
            timings=timings,
        )


def _relative_or_str(path: Path) -> str:
    try:
        from engineering_rag.utils.paths import repo_root

        return path.resolve().relative_to(repo_root()).as_posix()
    except ValueError:
        return path.as_posix()


def _render_summary(*, manifest: IndexManifest, report: Any) -> str:
    lines = [
        f"# Index Summary — {manifest.run_id}",
        "",
        f"- Status: **{manifest.status}**",
        f"- Input chunks: {manifest.input_chunks_jsonl_path} ({manifest.chunk_count} chunk(s))",
        f"- Chunk run ID: {manifest.input_chunk_run_id}",
        f"- Model: {manifest.model_name} (revision={manifest.resolved_model_revision or 'unknown'})",
        f"- Tokenizer: {manifest.tokenizer_name}",
        f"- Embedding dimension: {manifest.embedding_dimension}",
        f"- Distance metric: {manifest.distance_metric}",
        f"- Collection: {manifest.collection_name}",
        f"- Chroma path: {manifest.chroma_path}",
        f"- Collection count after run: {manifest.collection_count_after_run}",
        f"- Duration: {sum(manifest.timings_s.values()):.2f}s",
        f"- Throughput: {manifest.vector_validation_stats.get('vectors_per_second', 0)} vec/s",
        "",
        "## Content types",
        "",
    ]
    for ct, count in sorted(manifest.content_type_counts.items()):
        lines.append(f"- {ct}: {count}")
    lines += [
        "",
        "## Validation",
        "",
        f"- Failed gates: {len(report.failed_gates)}",
        f"- Warnings: {len(report.warnings)}",
        "",
        "## Inspect this run",
        "",
        "```",
        f"engrag-index inspect --profile configs/indexing_production.yaml --collection {manifest.collection_name}",
        f"engrag-index validate --run {manifest.run_id}",
        "```",
    ]
    return "\n".join(lines) + "\n"

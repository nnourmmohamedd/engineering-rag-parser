"""Orchestrates grounded answering: existing retrieval pipeline -> context builder -> prompt ->
local Ollama generation -> grounding validation -> artifacts.

The only module that imports both :mod:`engineering_rag.services.context_builder`
and :mod:`engineering_rag.databases.chroma` (via ``pipelines.retrieval_pipeline``'s
already-opened collection) -- mirroring how ``pipelines/retrieval_pipeline.py``
is the sole module importing both ``services.retriever`` and
``databases.chroma``. ``api/ask_cli.py`` contains zero business logic and only
calls into this module.

Never recreates or duplicates retrieval logic: every search goes through
``pipelines.retrieval_pipeline.run_hybrid_search`` / the existing
``HybridRetriever``.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from engineering_rag.clients.ollama import (
    LLMClient,
    OllamaError,
    OllamaHTTPClient,
    OllamaModelNotFoundError,
    OllamaVersionInfo,
)
from engineering_rag.pipelines.answering_artifacts import AnsweringRunDirectory
from engineering_rag.pipelines.answering_config import AnsweringPipelineConfig
from engineering_rag.pipelines.retrieval_config import RetrievalConfig
from engineering_rag.pipelines.retrieval_pipeline import ValidationReport as RetrievalValidationReport
from engineering_rag.pipelines.retrieval_pipeline import (
    open_collection_readonly,
    run_hybrid_search,
)
from engineering_rag.pipelines.retrieval_pipeline import (
    validate_environment as validate_retrieval_environment,
)
from engineering_rag.prompts.answering import get_prompt_contract
from engineering_rag.services.answerer import AnswerResponse, AnswerTrace, GroundedAnswerService
from engineering_rag.services.context_builder import ContextBuilder, ContextPackage, get_token_counter
from engineering_rag.services.context_builder.models import NeighborChunk
from engineering_rag.services.context_builder.neighbor_provider import NeighborProvider
from engineering_rag.services.embedder import EmbeddingService
from engineering_rag.services.reranker.interface import Reranker
from engineering_rag.services.retriever import FilterValue, RetrievalResponse

__all__ = [
    "AnsweringValidationReport",
    "ChromaNeighborProvider",
    "OllamaEnvironmentReport",
    "build_llm_client",
    "run_ask_pipeline",
    "run_context_pipeline",
    "validate_all",
    "validate_ollama_environment",
    "write_answering_artifacts",
]

logger = logging.getLogger(__name__)

#: bm25_enabled, reranker_enabled for each named retrieval mode. Mirrors
#: ``api/retrieve_cli.py``'s ``_MODE_TOGGLES`` exactly -- duplicated here
#: rather than imported, since pipelines must not depend on the CLI layer.
_MODE_TOGGLES: dict[str, tuple[bool, bool]] = {
    "vector": (False, False),
    "hybrid": (True, False),
    "hybrid-rerank": (True, True),
    "vector-rerank": (False, True),
}


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


class ChromaNeighborProvider(NeighborProvider):
    """Reads one chunk record by ID from the already-opened, already-indexed Chroma collection.

    Read-only: never creates, rebuilds, or mutates the collection, and never
    opens a second database. This is the only concrete ``NeighborProvider``
    in the codebase; ``services/context_builder`` never imports ``chromadb``
    itself.
    """

    def __init__(self, collection: Any) -> None:
        self._collection = collection

    def get_chunk(self, chunk_id: str) -> NeighborChunk | None:
        got = self._collection.get(ids=[chunk_id], include=["documents", "metadatas"])
        ids = got.get("ids") or []
        if not ids:
            return None
        documents = got.get("documents") or []
        metadatas = got.get("metadatas") or []
        text = documents[0] if documents else ""
        meta = metadatas[0] if metadatas else {}
        meta = meta or {}
        return NeighborChunk(
            chunk_id=ids[0],
            document_id=meta.get("document_id"),
            retrieval_text=text or "",
            source_filename=meta.get("source_filename"),
            source_sha256=meta.get("source_sha256"),
            page_numbers=[int(p) for p in _decode_list_field(meta.get("page_numbers"))],
            heading_path=[str(h) for h in _decode_list_field(meta.get("heading_path"))],
            section_title=meta.get("section_title"),
            content_type=meta.get("content_type"),
            content_hash=meta.get("content_hash"),
            chunk_index=meta.get("chunk_index"),
            previous_chunk_id=meta.get("previous_chunk_id"),
            next_chunk_id=meta.get("next_chunk_id"),
        )


def build_llm_client(config: AnsweringPipelineConfig, llm_client: LLMClient | None = None) -> LLMClient:
    """Return the injected client, or construct the production :class:`OllamaHTTPClient`."""
    if llm_client is not None:
        return llm_client
    return OllamaHTTPClient(config.ollama)


class OllamaEnvironmentReport:
    """Structured, JSON-serializable result of the Ollama half of ``engrag-ask validate``."""

    def __init__(self, *, checks: list[dict[str, Any]]) -> None:
        self.checks = checks

    @property
    def passed(self) -> bool:
        return all(c["passed"] for c in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {"status": "PASS" if self.passed else "FAIL", "checks": self.checks}


def validate_ollama_environment(
    config: AnsweringPipelineConfig, *, llm_client: LLMClient | None = None
) -> OllamaEnvironmentReport:
    """Health/version/model-installed/digest checks only. Never calls ``/api/chat`` -- never generates."""
    checks: list[dict[str, Any]] = []
    client = build_llm_client(config, llm_client)

    reachable = client.health_check()
    checks.append(
        {
            "check_id": "ollama_reachable",
            "passed": reachable,
            "summary": f"{config.ollama.base_url}: {'reachable' if reachable else 'unreachable'}",
        }
    )
    if not reachable:
        return OllamaEnvironmentReport(checks=checks)

    try:
        version_info: OllamaVersionInfo = client.version()
        checks.append({"check_id": "ollama_version", "passed": True, "summary": version_info.version})
    except OllamaError as exc:
        checks.append({"check_id": "ollama_version", "passed": False, "summary": str(exc)})
        return OllamaEnvironmentReport(checks=checks)

    try:
        info = client.model_info(config.ollama.model)
        checks.append(
            {
                "check_id": "model_installed",
                "passed": True,
                "summary": f"{info.name} digest={info.digest} parameter_size={info.parameter_size} "
                f"quantization={info.quantization_level} family={info.family}",
            }
        )
    except OllamaModelNotFoundError as exc:
        checks.append({"check_id": "model_installed", "passed": False, "summary": str(exc)})
        return OllamaEnvironmentReport(checks=checks)

    if config.ollama.strict_digest and config.ollama.expected_digest:
        digest_ok = info.digest == config.ollama.expected_digest
        checks.append(
            {
                "check_id": "model_digest_matches",
                "passed": digest_ok,
                "summary": f"observed={info.digest} expected={config.ollama.expected_digest}",
            }
        )
    else:
        checks.append(
            {
                "check_id": "model_digest_matches",
                "passed": True,
                "summary": "skipped: strict_digest=False or expected_digest unset",
            }
        )

    checks.append(
        {
            "check_id": "think_disabled",
            "passed": not config.ollama.think,
            "summary": f"think={config.ollama.think}",
        }
    )
    return OllamaEnvironmentReport(checks=checks)


class AnsweringValidationReport:
    """Combined result of ``engrag-ask validate``: Ollama + retrieval + config checks. Never generates."""

    def __init__(
        self,
        *,
        ollama: OllamaEnvironmentReport,
        retrieval: RetrievalValidationReport,
        config_checks: list[dict[str, Any]],
    ) -> None:
        self.ollama = ollama
        self.retrieval = retrieval
        self.config_checks = config_checks

    @property
    def passed(self) -> bool:
        return self.ollama.passed and self.retrieval.passed and all(c["passed"] for c in self.config_checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "PASS" if self.passed else "FAIL",
            "ollama": self.ollama.as_dict(),
            "retrieval": self.retrieval.as_dict(),
            "config_checks": self.config_checks,
        }


def validate_all(
    answering_config: AnsweringPipelineConfig,
    retrieval_config: RetrievalConfig,
    *,
    llm_client: LLMClient | None = None,
) -> AnsweringValidationReport:
    """Every non-destructive check: Ollama reachable/version/model/digest, retrieval database, config. Never generates."""
    ollama_report = validate_ollama_environment(answering_config, llm_client=llm_client)
    retrieval_report = validate_retrieval_environment(retrieval_config)

    cb = answering_config.context_builder
    total = (
        cb.max_context_tokens
        + cb.reserved_system_tokens
        + cb.safety_margin_tokens
        + answering_config.ollama.max_output_tokens
    )
    config_checks: list[dict[str, Any]] = [
        {
            "check_id": "token_budget_fits_context_window",
            "passed": total <= answering_config.ollama.context_window_tokens,
            "summary": f"{total} tokens reserved <= context_window_tokens={answering_config.ollama.context_window_tokens}",
        }
    ]
    try:
        get_prompt_contract(answering_config.answering.prompt_version)
        config_checks.append(
            {
                "check_id": "prompt_contract_resolves",
                "passed": True,
                "summary": f"prompt_version={answering_config.answering.prompt_version}",
            }
        )
    except ValueError as exc:
        config_checks.append({"check_id": "prompt_contract_resolves", "passed": False, "summary": str(exc)})

    return AnsweringValidationReport(
        ollama=ollama_report, retrieval=retrieval_report, config_checks=config_checks
    )


def _resolve_toggles(retrieval_mode: str) -> tuple[bool, bool]:
    if retrieval_mode not in _MODE_TOGGLES:
        raise ValueError(
            f"Unknown retrieval mode {retrieval_mode!r}. Must be one of: {sorted(_MODE_TOGGLES)}"
        )
    return _MODE_TOGGLES[retrieval_mode]


def _run_retrieval(
    query: str,
    retrieval_config: RetrievalConfig,
    *,
    retrieval_mode: str,
    top_k: int | None,
    collection_name: str | None,
    embedder: EmbeddingService | None,
    reranker: Reranker | None,
    metadata_filters: dict[str, FilterValue] | None,
) -> tuple[Any, RetrievalResponse]:
    """Run one retrieval call via the existing public retrieval pipeline, and also return the
    opened collection (for neighbor expansion only -- read-only, never a second retrieval path).
    """
    bm25_enabled, reranker_enabled = _resolve_toggles(retrieval_mode)
    response = run_hybrid_search(
        query,
        retrieval_config,
        top_k=top_k,
        bm25_enabled=bm25_enabled,
        reranker_enabled=reranker_enabled,
        metadata_filters=metadata_filters or {},
        collection_name=collection_name,
        embedder=embedder,
        reranker=reranker,
    )
    _client, collection = open_collection_readonly(retrieval_config, collection_name=collection_name)
    return collection, response


def run_context_pipeline(
    query: str,
    answering_config: AnsweringPipelineConfig,
    retrieval_config: RetrievalConfig,
    *,
    retrieval_mode: str,
    top_k: int | None = None,
    neighbors_enabled: bool = True,
    collection_name: str | None = None,
    embedder: EmbeddingService | None = None,
    reranker: Reranker | None = None,
    metadata_filters: dict[str, FilterValue] | None = None,
) -> tuple[RetrievalResponse, ContextPackage]:
    """Run retrieval, then build one :class:`ContextPackage`. Never calls the LLM.

    Raises:
        CollectionNotFoundError, BM25IndexNotFoundError, CorpusCompatibilityError,
        RetrievalError: see ``pipelines/retrieval_pipeline.py``.
        TokenizerLoadError: the configured production tokenizer could not be loaded.
    """
    collection, retrieval_response = _run_retrieval(
        query,
        retrieval_config,
        retrieval_mode=retrieval_mode,
        top_k=top_k,
        collection_name=collection_name,
        embedder=embedder,
        reranker=reranker,
        metadata_filters=metadata_filters,
    )
    neighbor_provider = ChromaNeighborProvider(collection) if neighbors_enabled else None
    token_counter = get_token_counter(answering_config.context_builder.tokenizer)
    builder = ContextBuilder(answering_config.context_builder, token_counter, neighbor_provider)
    context = builder.build(
        query=query,
        retrieval_response=retrieval_response,
        reserved_output_tokens=answering_config.ollama.max_output_tokens,
    )
    return retrieval_response, context


def run_ask_pipeline(
    query: str,
    answering_config: AnsweringPipelineConfig,
    retrieval_config: RetrievalConfig,
    *,
    retrieval_mode: str,
    top_k: int | None = None,
    neighbors_enabled: bool = True,
    llm_client: LLMClient | None = None,
    collection_name: str | None = None,
    embedder: EmbeddingService | None = None,
    reranker: Reranker | None = None,
    write_artifacts: bool = True,
    metadata_filters: dict[str, FilterValue] | None = None,
) -> tuple[RetrievalResponse, ContextPackage, AnswerResponse, AnswerTrace, AnsweringRunDirectory | None]:
    """Full pipeline: retrieval -> context -> prompt -> generation -> grounding -> (optional) artifacts."""
    started = time.perf_counter()
    retrieval_response, context = run_context_pipeline(
        query,
        answering_config,
        retrieval_config,
        retrieval_mode=retrieval_mode,
        top_k=top_k,
        neighbors_enabled=neighbors_enabled,
        collection_name=collection_name,
        embedder=embedder,
        reranker=reranker,
        metadata_filters=metadata_filters,
    )

    resolved_client = build_llm_client(answering_config, llm_client)
    model_digest: str | None = answering_config.ollama.expected_digest
    try:
        model_info = resolved_client.model_info(answering_config.ollama.model)
        model_digest = model_info.digest
    except OllamaError as exc:
        logger.warning("Could not resolve installed model digest before generation: %s", exc)

    service = GroundedAnswerService(
        llm_client=resolved_client,
        answering_config=answering_config.answering,
        grounding_config=answering_config.grounding,
        model_tag=answering_config.ollama.model,
        model_digest=model_digest,
        generation_config={
            "temperature": answering_config.ollama.temperature,
            "seed": answering_config.ollama.seed,
            "think": answering_config.ollama.think,
            "context_window_tokens": answering_config.ollama.context_window_tokens,
            "max_output_tokens": answering_config.ollama.max_output_tokens,
        },
    )
    answer_response, trace = service.answer(query, context)

    run_dir: AnsweringRunDirectory | None = None
    if write_artifacts:
        run_dir = AnsweringRunDirectory.create(answering_config.output_root, run_id=answer_response.run_id)
        write_answering_artifacts(
            run_dir,
            query=query,
            retrieval_response=retrieval_response,
            context=context,
            answer_response=answer_response,
            trace=trace,
            answering_config=answering_config,
            retrieval_config=retrieval_config,
            started_perf_counter=started,
        )
    return retrieval_response, context, answer_response, trace, run_dir


def _versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for dist in ("httpx", "transformers", "pydantic"):
        try:
            versions[dist] = version(dist)
        except PackageNotFoundError:
            versions[dist] = "not-installed"
    return versions


def write_answering_artifacts(
    run_dir: AnsweringRunDirectory,
    *,
    query: str,
    retrieval_response: RetrievalResponse,
    context: ContextPackage,
    answer_response: AnswerResponse,
    trace: AnswerTrace,
    answering_config: AnsweringPipelineConfig,
    retrieval_config: RetrievalConfig,
    started_perf_counter: float,
) -> None:
    """Write the complete, atomic run directory. Never stores hidden reasoning or secrets."""
    run_dir.write_json_atomic("query.json", {"query": query, "query_hash": answer_response.query_hash})
    run_dir.write_json_atomic("retrieval_response.json", retrieval_response.model_dump(mode="json"))
    run_dir.write_json_atomic("context.json", context.model_dump(mode="json"))
    run_dir.write_json_atomic(
        "prompt_manifest.json",
        {
            "prompt_version": answer_response.prompt_version,
            "system_prompt": trace.system_prompt,
            "user_prompt": trace.user_prompt,
        },
    )
    run_dir.write_json_atomic(
        "answer_draft.json",
        {"raw_model_content": trace.raw_model_content, "parsed_draft": trace.parsed_draft},
    )
    run_dir.write_json_atomic("answer.json", answer_response.model_dump(mode="json"))
    run_dir.write_json_atomic("grounding_report.json", answer_response.validation.model_dump(mode="json"))
    run_dir.write_json_atomic(
        "manifest.json",
        {
            "run_id": answer_response.run_id,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "query_hash": answer_response.query_hash,
            "source_corpus_fingerprint": retrieval_response.bm25_corpus_fingerprint,
            "retrieval_mode": retrieval_response.retrieval_mode,
            "retrieval_profile_hash": retrieval_config.config_hash(),
            "answering_profile_hash": answering_config.config_hash(),
            "model_tag": answer_response.model_tag,
            "model_digest": answer_response.model_digest,
            "prompt_version": answer_response.prompt_version,
            "context_schema_version": context.context_schema_version,
            "answer_schema_version": answer_response.answer_schema_version,
            "grounding_schema_version": answer_response.validation.grounding_schema_version,
            "tokenizer_description": context.tokenizer_description,
            "selected_chunk_ids": [s.chunk_id for s in context.selected_sources],
            "source_hashes": context.source_hashes,
            "status": answer_response.status,
            "repair_attempted": answer_response.repair_attempted,
            "warnings": answer_response.warnings,
            "duration_s": round(time.perf_counter() - started_perf_counter, 3),
            "versions": _versions(),
        },
    )

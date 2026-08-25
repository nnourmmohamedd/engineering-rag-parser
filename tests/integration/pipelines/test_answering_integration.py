"""End-to-end grounded-answering integration test: real (ephemeral) Chroma +
real ContextBuilder + real GroundedAnswerService + real GroundingReport
validation, driven by a fake embedder and a fake LLM client -- proving the
full wiring (retrieval -> context -> prompt -> parse -> grounding -> artifacts)
without any network access or real model/Ollama dependency.

Mirrors ``test_hybrid_retrieval_integration.py``'s fixture pattern.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engineering_rag.databases.chroma import (
    CollectionIdentity,
    chroma_safe_metadata,
    content_hash,
    get_client,
    ingest_batch,
    open_or_create_collection,
)
from engineering_rag.databases.chroma.config import ChromaConfig
from engineering_rag.pipelines.answering_config import AnsweringPipelineConfig
from engineering_rag.pipelines.answering_pipeline import run_ask_pipeline, run_context_pipeline
from engineering_rag.pipelines.retrieval_config import RetrievalConfig
from tests.support.fake_embedder import FakeEmbeddingService
from tests.support.fake_llm_client import FakeLLMClient, make_answer_payload, scripted_json

pytestmark = pytest.mark.integration

_MODEL_NAME = "fake-embedder-for-tests"

_PASSAGES = {
    "chunk_feed": "FEED develops the control philosophy and major design deliverables for the project.",
    "chunk_wiring": "Loop wiring diagrams show the electrical signal path for one control loop.",
    "chunk_valve": "Control valves regulate flow according to the process control philosophy.",
}


def _build_collection(tmp_path: Path) -> ChromaConfig:
    chroma_config = ChromaConfig(persistence_path=tmp_path / "chroma", collection_name="integration_test")
    embedder = FakeEmbeddingService(model_name=_MODEL_NAME)
    ids = list(_PASSAGES)
    texts = list(_PASSAGES.values())
    records, _stats = embedder.embed_passages(ids, texts)

    client = get_client(chroma_config.persistence_path)
    identity = CollectionIdentity(
        model_name=_MODEL_NAME, embedding_dimension=768, distance_metric="cosine", tokenizer_name=_MODEL_NAME
    )
    collection = open_or_create_collection(client, chroma_config, identity)

    metadatas = []
    for cid, text in zip(ids, texts, strict=True):
        meta = chroma_safe_metadata(
            {
                "document_id": "doc1",
                "source_filename": "integration.pdf",
                "chunk_index": ids.index(cid),
                "content_type": "text",
                "page_numbers": [1],
                "heading_path": ["Root"],
                "chunk_schema_version": "1.0.0",
            }
        )
        meta["content_hash"] = content_hash(text, meta)
        metadatas.append(meta)

    ingest_batch(
        collection,
        ids=ids,
        embeddings=[r.vector for r in records],
        documents=texts,
        metadatas=metadatas,
        idempotent=True,
    )
    return chroma_config


def _retrieval_config(tmp_path: Path, chroma_config: ChromaConfig) -> RetrievalConfig:
    return RetrievalConfig(embedding={"model_name": _MODEL_NAME}, chroma=chroma_config)


def _answering_config() -> AnsweringPipelineConfig:
    return AnsweringPipelineConfig(
        context_builder={"tokenizer": {"backend": "conservative_fallback"}, "max_context_tokens": 2000}
    )


class TestContextPipeline:
    def test_context_pipeline_never_touches_llm(self, tmp_path: Path) -> None:
        chroma_config = _build_collection(tmp_path)
        retrieval_config = _retrieval_config(tmp_path, chroma_config)
        answering_config = _answering_config()

        _retrieval_response, context = run_context_pipeline(
            "control philosophy",
            answering_config,
            retrieval_config,
            retrieval_mode="vector",
            embedder=FakeEmbeddingService(model_name=_MODEL_NAME),
        )
        assert context.total_sources_selected > 0
        assert context.selected_sources[0].citation_id == "S1"


class TestAskPipeline:
    def test_grounded_answer_end_to_end(self, tmp_path: Path) -> None:
        chroma_config = _build_collection(tmp_path)
        retrieval_config = _retrieval_config(tmp_path, chroma_config)
        answering_config = _answering_config()

        # Discover the real citation id assigned for the top hit, then script a matching answer.
        _retrieval_response, context = run_context_pipeline(
            "control philosophy",
            answering_config,
            retrieval_config,
            retrieval_mode="vector",
            embedder=FakeEmbeddingService(model_name=_MODEL_NAME),
        )
        top = context.selected_sources[0]
        payload = make_answer_payload(
            answer=f"FEED develops the control philosophy [{top.citation_id}].",
            citations_used=[top.citation_id],
            supporting_evidence=[
                {"citation_id": top.citation_id, "supporting_quote": top.retrieval_text[:30]}
            ],
        )
        llm_client = FakeLLMClient(responses=[scripted_json(payload)])

        _rr, _ctx, answer, _trace, run_dir = run_ask_pipeline(
            "control philosophy",
            answering_config,
            retrieval_config,
            retrieval_mode="vector",
            embedder=FakeEmbeddingService(model_name=_MODEL_NAME),
            llm_client=llm_client,
        )

        assert answer.status == "answered"
        assert answer.validation.status == "PASS"
        assert run_dir is not None
        for name in (
            "query.json",
            "retrieval_response.json",
            "context.json",
            "prompt_manifest.json",
            "answer_draft.json",
            "answer.json",
            "grounding_report.json",
            "manifest.json",
        ):
            assert (run_dir.root / name).is_file(), f"missing artifact: {name}"

        manifest = json.loads((run_dir.root / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["status"] == "answered"
        assert manifest["retrieval_mode"] == "vector"

        prompt_manifest = json.loads((run_dir.root / "prompt_manifest.json").read_text(encoding="utf-8"))
        assert "system_prompt" in prompt_manifest
        assert "user_prompt" in prompt_manifest
        assert "reasoning" not in prompt_manifest  # never stores hidden chain-of-thought

    def test_unanswerable_question_refuses(self, tmp_path: Path) -> None:
        chroma_config = _build_collection(tmp_path)
        retrieval_config = _retrieval_config(tmp_path, chroma_config)
        answering_config = _answering_config()
        payload = make_answer_payload(
            answer="I could not find enough evidence in the indexed documents to answer this question reliably.",
            insufficient_evidence=True,
            insufficiency_reason="No relevant evidence about world cups in this engineering corpus.",
        )
        llm_client = FakeLLMClient(responses=[scripted_json(payload)])

        _rr, _ctx, answer, _trace, _run_dir = run_ask_pipeline(
            "Who won the FIFA World Cup in 2030?",
            answering_config,
            retrieval_config,
            retrieval_mode="vector",
            embedder=FakeEmbeddingService(model_name=_MODEL_NAME),
            llm_client=llm_client,
        )
        assert answer.status == "insufficient_evidence"

    def test_all_four_retrieval_modes_connect_to_answering(self, tmp_path: Path) -> None:
        chroma_config = _build_collection(tmp_path)
        retrieval_config = _retrieval_config(tmp_path, chroma_config)
        answering_config = _answering_config()
        payload = make_answer_payload(
            answer="See evidence.", insufficient_evidence=True, insufficiency_reason="n/a"
        )

        for mode in ("vector", "hybrid", "vector-rerank", "hybrid-rerank"):
            from engineering_rag.pipelines.retrieval_pipeline import build_bm25_index_pipeline
            from tests.support.fake_reranker import FakeReranker

            if mode in ("hybrid", "hybrid-rerank"):
                build_bm25_index_pipeline(retrieval_config, force=True)

            llm_client = FakeLLMClient(responses=[scripted_json(payload)])
            reranker = FakeReranker() if mode in ("vector-rerank", "hybrid-rerank") else None
            _rr, _ctx, answer, _trace, _run_dir = run_ask_pipeline(
                "control philosophy",
                answering_config,
                retrieval_config,
                retrieval_mode=mode,
                embedder=FakeEmbeddingService(model_name=_MODEL_NAME),
                llm_client=llm_client,
                reranker=reranker,
            )
            assert answer.retrieval_mode == mode, f"mode {mode} did not propagate"

"""End-to-end hybrid retrieval integration test: real (ephemeral) Chroma +
real persistent BM25 index (bm25s) + RRF fusion + a fake cross-encoder,
proving every mode's wiring without any network access or real model
download.

Mirrors ``test_retrieval_integration.py``'s fixture pattern exactly, extended
with a BM25 index built from the identical collection.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_rag.databases.bm25.config import BM25Config
from engineering_rag.databases.chroma import (
    CollectionIdentity,
    chroma_safe_metadata,
    content_hash,
    get_client,
    ingest_batch,
    open_or_create_collection,
)
from engineering_rag.databases.chroma.config import ChromaConfig
from engineering_rag.pipelines.retrieval_config import RetrievalConfig
from engineering_rag.pipelines.retrieval_pipeline import build_bm25_index_pipeline, run_hybrid_search
from engineering_rag.services.retriever import CorpusCompatibilityError
from tests.support.fake_embedder import FakeEmbeddingService
from tests.support.fake_reranker import FakeReranker

pytestmark = pytest.mark.integration

_MODEL_NAME = "fake-embedder-for-tests"

_PASSAGES = {
    "chunk_control": "The control philosophy defines automated operating principles for PT-101.",
    "chunk_wiring": "Loop wiring diagrams show the electrical signal path for one control loop.",
    "chunk_table": "Table 1 lists C&I deliverables by project phase per IEC 61511.",
    "chunk_feed": "Front-End Engineering Design FEED activities begin the project lifecycle.",
}


def _build_collection(tmp_path: Path, *, source_filenames: dict[str, str] | None = None) -> ChromaConfig:
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

    filenames = source_filenames or dict.fromkeys(ids, "integration.pdf")
    metadatas = []
    for cid, text in zip(ids, texts, strict=True):
        meta = chroma_safe_metadata(
            {
                "document_id": "doc1",
                "source_filename": filenames[cid],
                "chunk_index": ids.index(cid),
                "content_type": "table" if cid == "chunk_table" else "text",
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


def _config(tmp_path: Path, chroma_config: ChromaConfig) -> RetrievalConfig:
    return RetrievalConfig(
        embedding={"model_name": _MODEL_NAME},
        chroma=chroma_config,
        bm25=BM25Config(index_path=str(tmp_path / "bm25")),
    )


class TestHybridModes:
    def test_vector_mode_unaffected_by_hybrid_wiring(self, tmp_path: Path) -> None:
        chroma_config = _build_collection(tmp_path)
        config = _config(tmp_path, chroma_config)
        response = run_hybrid_search(
            "control philosophy", config, embedder=FakeEmbeddingService(model_name=_MODEL_NAME), top_k=2
        )
        assert response.retrieval_mode == "vector"
        assert response.bm25_enabled is False
        assert response.reranker_enabled is False
        assert response.returned_count == 2

    def test_hybrid_mode_fuses_vector_and_bm25(self, tmp_path: Path) -> None:
        chroma_config = _build_collection(tmp_path)
        config = _config(tmp_path, chroma_config)
        build_bm25_index_pipeline(config)

        response = run_hybrid_search(
            "PT-101 control",
            config,
            embedder=FakeEmbeddingService(model_name=_MODEL_NAME),
            bm25_enabled=True,
            top_k=4,
        )
        assert response.retrieval_mode == "hybrid"
        assert response.candidate_counts["bm25"] > 0
        assert response.candidate_counts["fused"] > 0
        assert all(h.rrf_score is not None for h in response.hits)
        assert all(h.rrf_rank is not None for h in response.hits)

    def test_hybrid_rerank_mode_reorders_via_fake_reranker(self, tmp_path: Path) -> None:
        chroma_config = _build_collection(tmp_path)
        config = _config(tmp_path, chroma_config)
        build_bm25_index_pipeline(config)
        reranker = FakeReranker()

        response = run_hybrid_search(
            "IEC 61511 deliverables",
            config,
            embedder=FakeEmbeddingService(model_name=_MODEL_NAME),
            bm25_enabled=True,
            reranker_enabled=True,
            reranker=reranker,
            top_k=3,
        )
        assert response.retrieval_mode == "hybrid-rerank"
        assert response.candidate_counts["reranked"] > 0
        assert reranker.calls  # the reranker was actually invoked
        assert all(h.reranker_rank is not None for h in response.hits)
        assert all(h.reranker_score is not None for h in response.hits)

    def test_vector_rerank_mode_never_loads_bm25(self, tmp_path: Path) -> None:
        chroma_config = _build_collection(tmp_path)
        config = _config(tmp_path, chroma_config)
        # deliberately do NOT build a BM25 index — vector-rerank must not need one
        reranker = FakeReranker()

        response = run_hybrid_search(
            "FEED activities",
            config,
            embedder=FakeEmbeddingService(model_name=_MODEL_NAME),
            bm25_enabled=False,
            reranker_enabled=True,
            reranker=reranker,
            top_k=2,
        )
        assert response.retrieval_mode == "vector-rerank"
        assert response.bm25_enabled is False
        assert "bm25" not in response.candidate_counts


class TestCorpusCompatibilityGate:
    def test_refuses_hybrid_search_after_collection_diverges(self, tmp_path: Path) -> None:
        chroma_config = _build_collection(tmp_path)
        config = _config(tmp_path, chroma_config)
        build_bm25_index_pipeline(config)

        # Simulate the BM25 index going stale relative to Chroma by corrupting
        # its manifest's chunk_ids after the fact (never done by production code).
        manifest_path = Path(config.bm25.index_path) / "bm25_manifest.json"
        import json

        data = json.loads(manifest_path.read_text())
        data["chunk_ids"] = data["chunk_ids"][:-1]
        data["corpus_count"] -= 1
        manifest_path.write_text(json.dumps(data))

        with pytest.raises(CorpusCompatibilityError):
            run_hybrid_search(
                "control philosophy",
                config,
                embedder=FakeEmbeddingService(model_name=_MODEL_NAME),
                bm25_enabled=True,
            )


class TestFiltersAcrossModes:
    def test_filter_excludes_document_in_hybrid_mode(self, tmp_path: Path) -> None:
        chroma_config = _build_collection(
            tmp_path,
            source_filenames={
                "chunk_control": "a.pdf",
                "chunk_wiring": "a.pdf",
                "chunk_table": "b.pdf",
                "chunk_feed": "b.pdf",
            },
        )
        config = _config(tmp_path, chroma_config)
        build_bm25_index_pipeline(config)

        response = run_hybrid_search(
            "deliverables",
            config,
            embedder=FakeEmbeddingService(model_name=_MODEL_NAME),
            bm25_enabled=True,
            metadata_filters={"source_filename": "a.pdf"},
            top_k=10,
        )
        assert response.hits
        assert all(h.source_filename == "a.pdf" for h in response.hits)


class TestNoMutation:
    def test_hybrid_search_never_grows_chroma_or_bm25(self, tmp_path: Path) -> None:
        chroma_config = _build_collection(tmp_path)
        config = _config(tmp_path, chroma_config)
        build_bm25_index_pipeline(config)

        client = get_client(chroma_config.persistence_path)
        collection = client.get_collection(name="integration_test")
        before = collection.count()

        for _ in range(3):
            run_hybrid_search(
                "control", config, embedder=FakeEmbeddingService(model_name=_MODEL_NAME), bm25_enabled=True
            )

        assert collection.count() == before

    def test_bm25_rebuild_is_atomic_and_idempotent(self, tmp_path: Path) -> None:
        chroma_config = _build_collection(tmp_path)
        config = _config(tmp_path, chroma_config)
        manifest_1 = build_bm25_index_pipeline(config)
        manifest_2 = build_bm25_index_pipeline(config)
        assert manifest_1.corpus_fingerprint == manifest_2.corpus_fingerprint
        assert Path(config.bm25.index_path).is_dir()
        # no stray `.building-*`/`.previous-*` directories left behind
        siblings = {p.name for p in Path(config.bm25.index_path).parent.iterdir()}
        assert siblings == {Path(config.bm25.index_path).name, "chroma"}

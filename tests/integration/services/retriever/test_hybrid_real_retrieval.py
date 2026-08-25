"""Real-corpus hybrid retrieval acceptance tests: the actual, already-built
BM25 index (``engrag-retrieve build-bm25``) and the real
``BAAI/bge-reranker-base`` cross-encoder, queried against the real
``engineering_documents_v1`` Chroma collection (122 chunks: 113 Engineering
PDF, 9 OCR PDF).

Marked ``slow`` — downloads/loads real model weights, excluded from
``pytest -m "not slow"`` CI. Self-skips if the local collection or the local
BM25 index is not present, mirroring
``tests/integration/services/retriever/test_bge_real_retrieval.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_rag.pipelines.retrieval_config import load_retrieval_config
from engineering_rag.pipelines.retrieval_pipeline import run_hybrid_search

pytestmark = pytest.mark.slow

_PROFILE = Path("configs/retrieval_production.yaml")


def _collection_available() -> bool:
    config = load_retrieval_config(_PROFILE)
    persistence_path = Path(config.chroma.persistence_path)
    return persistence_path.is_dir() and any(persistence_path.iterdir())


def _bm25_index_available() -> bool:
    config = load_retrieval_config(_PROFILE)
    index_path = Path(config.bm25.index_path)
    return (index_path / "bm25_manifest.json").is_file()


requires_real_collection = pytest.mark.skipif(
    not _collection_available(),
    reason="data/output/databases/chroma not present (run engrag-index build first)",
)
requires_real_bm25_index = pytest.mark.skipif(
    not _bm25_index_available(),
    reason="BM25 index not present (run `engrag-retrieve build-bm25 --profile "
    "configs/retrieval_production.yaml` first)",
)


@requires_real_collection
@requires_real_bm25_index
class TestRealHybridRetrieval:
    def test_hybrid_mode_returns_113_chunk_document_hit(self) -> None:
        config = load_retrieval_config(_PROFILE)
        response = run_hybrid_search("instrument index tag numbers", config, bm25_enabled=True, top_k=5)
        assert response.retrieval_mode == "hybrid"
        assert response.returned_count > 0
        assert any(h.bm25_rank is not None for h in response.hits)

    def test_hybrid_mode_finds_exact_identifier_bm25_helps_with(self) -> None:
        config = load_retrieval_config(_PROFILE)
        response = run_hybrid_search("IEC 61511", config, bm25_enabled=True, top_k=5)
        assert response.returned_count > 0
        assert response.candidate_counts.get("bm25", 0) > 0

    def test_ocr_document_reachable_in_hybrid_mode(self) -> None:
        config = load_retrieval_config(_PROFILE)
        response = run_hybrid_search(
            "OCR benchmark table accuracy",
            config,
            bm25_enabled=True,
            metadata_filters={"content_type": "table"},
            top_k=5,
        )
        assert response.returned_count > 0
        assert all(h.content_type == "table" for h in response.hits)

    def test_repeated_hybrid_queries_are_repeatable(self) -> None:
        config = load_retrieval_config(_PROFILE)
        r1 = run_hybrid_search("control valve", config, bm25_enabled=True, top_k=5)
        r2 = run_hybrid_search("control valve", config, bm25_enabled=True, top_k=5)
        assert [h.chunk_id for h in r1.hits] == [h.chunk_id for h in r2.hits]

    def test_hybrid_search_never_mutates_chroma_or_bm25(self) -> None:
        from engineering_rag.databases.chroma import get_client

        config = load_retrieval_config(_PROFILE)
        client = get_client(config.chroma.persistence_path)
        collection = client.get_collection(name=config.chroma.collection_name)
        before_count = collection.count()
        from engineering_rag.databases.bm25.index import load_bm25_index

        before_fingerprint = load_bm25_index(config.bm25).manifest.corpus_fingerprint

        run_hybrid_search("control valve", config, bm25_enabled=True, top_k=5)

        assert collection.count() == before_count
        assert load_bm25_index(config.bm25).manifest.corpus_fingerprint == before_fingerprint


@requires_real_collection
@requires_real_bm25_index
class TestRealCrossEncoderReranking:
    def test_hybrid_rerank_mode_loads_real_model_and_reranks(self) -> None:
        config = load_retrieval_config(_PROFILE)
        response = run_hybrid_search(
            "What is an instrument index?", config, bm25_enabled=True, reranker_enabled=True, top_k=5
        )
        assert response.retrieval_mode == "hybrid-rerank"
        assert response.reranker_model == "BAAI/bge-reranker-base"
        assert all(h.reranker_score is not None for h in response.hits)
        assert response.stage_latencies_s.get("reranker", 0) > 0

    def test_vector_rerank_mode_does_not_require_bm25(self) -> None:
        config = load_retrieval_config(_PROFILE)
        response = run_hybrid_search(
            "Explain the role of control valves.", config, bm25_enabled=False, reranker_enabled=True, top_k=3
        )
        assert response.retrieval_mode == "vector-rerank"
        assert response.candidate_counts.get("bm25") is None

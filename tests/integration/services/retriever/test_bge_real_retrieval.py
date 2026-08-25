"""Real-model retrieval acceptance tests: the actual BAAI/bge-base-en-v1.5 weights
queried against the actual, already-indexed ``engineering_documents_v1`` collection.

Marked ``slow`` (downloads/loads real model weights) — excluded from
``pytest -m "not slow"`` CI. Self-skips if the local collection produced by
``engrag-index build`` is not present, exactly like
``tests/integration/pipelines/test_acceptance_document.py`` self-skips
without the confidential PDF.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from engineering_rag.pipelines.retrieval_config import load_retrieval_config
from engineering_rag.pipelines.retrieval_pipeline import run_search

pytestmark = pytest.mark.slow

_PROFILE = Path("configs/retrieval_production.yaml")


def _collection_available() -> bool:
    config = load_retrieval_config(_PROFILE)
    persistence_path = Path(config.chroma.persistence_path)
    return persistence_path.is_dir() and any(persistence_path.iterdir())


requires_real_collection = pytest.mark.skipif(
    not _collection_available(),
    reason="data/output/databases/chroma not present (run engrag-index build first)",
)


@requires_real_collection
class TestRealRetrievalAgainstEngineeringDocuments:
    def test_query_returns_semantically_relevant_top_result(self) -> None:
        config = load_retrieval_config(_PROFILE)
        response = run_search("What is a Piping and Instrumentation Diagram?", config, top_k=3)
        assert response.returned_count > 0
        assert response.embedding_dimension == 768
        top = response.hits[0]
        assert "P&ID" in top.retrieval_text or "Piping and Instrumentation" in top.retrieval_text

    def test_ocr_document_is_queryable(self) -> None:
        config = load_retrieval_config(_PROFILE)
        response = run_search(
            "OCR benchmark table accuracy", config, top_k=5, metadata_filters={"content_type": "table"}
        )
        assert response.returned_count > 0
        assert all(h.content_type == "table" for h in response.hits)

    def test_query_vector_is_normalized_and_finite(self) -> None:
        from engineering_rag.services.embedder.bge import BGEEmbeddingService
        from engineering_rag.services.embedder.config import EmbedderConfig

        embedder = BGEEmbeddingService(EmbedderConfig())
        vector = embedder.embed_query("control system architecture")
        assert len(vector) == 768
        assert all(math.isfinite(v) for v in vector)
        norm = math.sqrt(sum(v * v for v in vector))
        assert abs(norm - 1.0) < 1e-3

    def test_repeated_queries_are_repeatable_within_tolerance(self) -> None:
        config = load_retrieval_config(_PROFILE)
        r1 = run_search("control philosophy", config, top_k=5)
        r2 = run_search("control philosophy", config, top_k=5)
        assert [h.chunk_id for h in r1.hits] == [h.chunk_id for h in r2.hits]
        for h1, h2 in zip(r1.hits, r2.hits, strict=True):
            assert h1.raw_distance == pytest.approx(h2.raw_distance, abs=1e-5)

    def test_provenance_fields_are_populated_for_real_chunks(self) -> None:
        config = load_retrieval_config(_PROFILE)
        response = run_search("cable schedule routing", config, top_k=3)
        for hit in response.hits:
            assert hit.source_filename
            assert hit.chunk_id
            assert hit.content_hash

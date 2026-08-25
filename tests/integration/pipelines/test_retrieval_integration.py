"""End-to-end retrieval integration test: query -> embedding -> temporary Chroma
collection -> top-k results -> serialized response.

Uses the deterministic :class:`FakeEmbeddingService` (no real model, no
network) and a real, ephemeral ``chromadb.PersistentClient`` rooted at
``tmp_path`` — the same combination the indexing pipeline's own integration
tests use, adapted for the query side.
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
from engineering_rag.pipelines.retrieval_config import RetrievalConfig
from engineering_rag.pipelines.retrieval_pipeline import run_search
from tests.support.fake_embedder import FakeEmbeddingService

pytestmark = pytest.mark.integration

_MODEL_NAME = "fake-embedder-for-tests"

_PASSAGES = {
    "chunk_control": "The control philosophy defines automated operating principles.",
    "chunk_wiring": "Loop wiring diagrams show the electrical signal path for one control loop.",
    "chunk_table": "Table 1 lists C&I deliverables by project phase.",
}


def _index_fixture_passages(tmp_path: Path) -> ChromaConfig:
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
                "source_filename": "integration.pdf",
                "chunk_index": ids.index(cid),
                "content_type": "table" if cid == "chunk_table" else "text",
                "page_numbers": [1],
                "heading_path": ["Root"],
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


class TestFullRetrievalRoundTrip:
    def test_query_to_serialized_top_k_response(self, tmp_path: Path) -> None:
        chroma_config = _index_fixture_passages(tmp_path)
        config = RetrievalConfig(embedding={"model_name": _MODEL_NAME}, chroma=chroma_config)

        response = run_search(
            "What does the control philosophy define?",
            config,
            embedder=FakeEmbeddingService(model_name=_MODEL_NAME),
            top_k=3,
        )

        assert response.returned_count == 3
        assert response.collection_name == "integration_test"
        assert response.embedding_model == _MODEL_NAME

        # Every hit carries the provenance fields set at index time.
        by_id = {h.chunk_id: h for h in response.hits}
        assert set(by_id) == set(_PASSAGES)
        assert by_id["chunk_table"].content_type == "table"
        assert by_id["chunk_control"].source_filename == "integration.pdf"
        assert by_id["chunk_control"].heading_path == ["Root"]

        # The full response is JSON-serializable and round-trips exactly.
        payload = json.loads(response.model_dump_json())
        assert payload["returned_count"] == 3

    def test_metadata_filter_narrows_to_the_table_chunk(self, tmp_path: Path) -> None:
        chroma_config = _index_fixture_passages(tmp_path)
        config = RetrievalConfig(embedding={"model_name": _MODEL_NAME}, chroma=chroma_config)

        response = run_search(
            "deliverables by phase",
            config,
            embedder=FakeEmbeddingService(model_name=_MODEL_NAME),
            top_k=10,
            metadata_filters={"content_type": "table"},
        )
        assert {h.chunk_id for h in response.hits} == {"chunk_table"}

    def test_repeated_calls_do_not_grow_the_collection(self, tmp_path: Path) -> None:
        chroma_config = _index_fixture_passages(tmp_path)
        config = RetrievalConfig(embedding={"model_name": _MODEL_NAME}, chroma=chroma_config)
        client = get_client(chroma_config.persistence_path)
        collection = client.get_collection(name="integration_test")
        before = collection.count()

        for _ in range(3):
            run_search("q", config, embedder=FakeEmbeddingService(model_name=_MODEL_NAME), top_k=2)

        assert collection.count() == before

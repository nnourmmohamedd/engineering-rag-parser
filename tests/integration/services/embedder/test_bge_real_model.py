"""Real-model acceptance tests: the actual BAAI/bge-base-en-v1.5 weights.

Marked ``slow`` (downloads/loads real model weights, minutes on first run) —
excluded from ``pytest -m "not slow"`` CI. Not run automatically by this
milestone's implementer; the mentor runs these during verification, using the
BGE-aligned chunker runs already produced under
``data/output/chunker/*/2026*-*/``.
"""

from __future__ import annotations

import math

import pytest

from engineering_rag.services.embedder.config import EmbedderConfig
from engineering_rag.services.embedder.errors import EmptyQueryError

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def embedder():  # noqa: ANN201
    from engineering_rag.services.embedder.bge import BGEEmbeddingService

    return BGEEmbeddingService(EmbedderConfig())


class TestBGEModelIdentity:
    def test_model_info_reports_768_dimensions(self, embedder) -> None:  # noqa: ANN001
        info = embedder.model_info()
        assert info.dimension == 768
        assert info.max_seq_length == 512
        assert info.model_name == "BAAI/bge-base-en-v1.5"

    def test_resolved_revision_is_reported(self, embedder) -> None:  # noqa: ANN001
        info = embedder.model_info()
        assert info.resolved_revision is not None
        assert len(info.resolved_revision) == 40  # a full git commit sha


class TestBGEPassageEmbedding:
    def test_passage_vector_is_normalized_768d(self, embedder) -> None:  # noqa: ANN001
        records, _stats = embedder.embed_passages(["c1"], ["The transmitter provides a 4-20 mA signal."])
        vec = records[0].vector
        assert len(vec) == 768
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 1e-3

    def test_batch_ordering_preserved(self, embedder) -> None:  # noqa: ANN001
        ids = [f"c{i}" for i in range(5)]
        texts = [f"Sentence number {i} about instrumentation." for i in range(5)]
        records, _stats = embedder.embed_passages(ids, texts)
        assert [r.chunk_id for r in records] == ids


class TestBGEQueryEmbedding:
    def test_query_prefix_changes_the_embedding(self, embedder) -> None:  # noqa: ANN001
        text = "pressure transmitter accuracy"
        passage_records, _ = embedder.embed_passages(["c1"], [text])
        query_vec = embedder.embed_query(text)
        assert passage_records[0].vector != query_vec

    def test_empty_query_rejected(self, embedder) -> None:  # noqa: ANN001
        with pytest.raises(EmptyQueryError):
            embedder.embed_query("   ")

    def test_query_vector_normalized_768d(self, embedder) -> None:  # noqa: ANN001
        vec = embedder.embed_query("what is the accuracy of FT-101?")
        assert len(vec) == 768
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 1e-3


class TestBGEChromaRoundTrip:
    def test_real_vectors_round_trip_through_chroma(self, embedder, tmp_path) -> None:  # noqa: ANN001
        from engineering_rag.databases.chroma.client import get_client
        from engineering_rag.databases.chroma.collection import open_or_create_collection
        from engineering_rag.databases.chroma.config import ChromaConfig
        from engineering_rag.databases.chroma.models import CollectionIdentity
        from engineering_rag.databases.chroma.repository import content_hash, ingest_batch
        from engineering_rag.databases.chroma.validation import round_trip_check, self_retrieval_check

        texts = [
            "The transmitter FT-101 provides a 4-20 mA signal at 24 V DC.",
            "Accuracy is 0.5% of span at 100 kPa, per ISA-5.1 and the P&ID.",
            "Section 2 covers control valve sizing and actuator selection.",
        ]
        ids = ["r1", "r2", "r3"]
        records, _ = embedder.embed_passages(ids, texts)
        vectors_by_id = {r.chunk_id: r.vector for r in records}

        config = ChromaConfig(persistence_path=tmp_path / "chroma", collection_name="bge_real_test")
        identity = CollectionIdentity(
            model_name="BAAI/bge-base-en-v1.5",
            embedding_dimension=768,
            distance_metric="cosine",
            tokenizer_name="BAAI/bge-base-en-v1.5",
        )
        client = get_client(config.persistence_path)
        collection = open_or_create_collection(client, config, identity)
        ingest_batch(
            collection,
            ids=ids,
            embeddings=[vectors_by_id[i] for i in ids],
            documents=texts,
            metadatas=[{"content_hash": content_hash(t, {})} for t in texts],
            idempotent=True,
        )

        problems = round_trip_check(
            collection, ids=ids, expected_documents=dict(zip(ids, texts, strict=True)), norm_tolerance=1e-3
        )
        assert problems == []

        failures = self_retrieval_check(collection, sample_ids=ids, vectors_by_id=vectors_by_id)
        assert failures == []

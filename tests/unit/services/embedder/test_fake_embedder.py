"""Tests for the deterministic fake embedder AND the behaviour contract it must
share with the real BGE implementation: no prefix on passages, exact prefix on
queries, empty-query rejection, deterministic ordering, dimension/normalization.
"""

from __future__ import annotations

import pytest

from engineering_rag.services.embedder.errors import EmptyQueryError
from tests.support.fake_embedder import FakeEmbeddingService


class TestFakeEmbedderContract:
    def test_deterministic_per_text(self) -> None:
        e = FakeEmbeddingService()
        records1, _ = e.embed_passages(["a"], ["hello world"])
        records2, _ = e.embed_passages(["a"], ["hello world"])
        assert records1[0].vector == records2[0].vector

    def test_different_text_different_vector(self) -> None:
        e = FakeEmbeddingService()
        records, _ = e.embed_passages(["a", "b"], ["hello", "goodbye"])
        assert records[0].vector != records[1].vector

    def test_vector_is_768d_and_normalized(self) -> None:
        e = FakeEmbeddingService()
        records, _ = e.embed_passages(["a"], ["hello"])
        vec = records[0].vector
        assert len(vec) == 768
        norm = sum(v * v for v in vec) ** 0.5
        assert abs(norm - 1.0) < 1e-6

    def test_batch_ordering_matches_input_order(self) -> None:
        e = FakeEmbeddingService()
        ids = [f"id{i}" for i in range(10)]
        texts = [f"text number {i}" for i in range(10)]
        records, _ = e.embed_passages(ids, texts)
        assert [r.chunk_id for r in records] == ids
        # Recompute independently and confirm order-independent determinism.
        for r, text in zip(records, texts, strict=True):
            expected, _ = e.embed_passages([r.chunk_id], [text])
            assert r.vector == expected[0].vector

    def test_passages_get_no_prefix_but_queries_do(self) -> None:
        e = FakeEmbeddingService()
        passage_records, _ = e.embed_passages(["a"], ["hello world"])
        query_vector = e.embed_query("hello world")
        # Since query has a prefix applied and passage does not, given a
        # deterministic hash-based embedder the two vectors must differ.
        assert passage_records[0].vector != query_vector

    def test_empty_query_rejected(self) -> None:
        e = FakeEmbeddingService()
        with pytest.raises(EmptyQueryError):
            e.embed_query("")

    def test_whitespace_only_query_rejected(self) -> None:
        e = FakeEmbeddingService()
        with pytest.raises(EmptyQueryError):
            e.embed_query("   \n\t  ")

    def test_mismatched_lengths_raise(self) -> None:
        e = FakeEmbeddingService()
        with pytest.raises(ValueError, match="length mismatch"):
            e.embed_passages(["a", "b"], ["only one"])

    def test_model_info_reports_dimension(self) -> None:
        e = FakeEmbeddingService()
        info = e.model_info()
        assert info.dimension == 768
        assert info.normalize_embeddings is True

    def test_health_check_does_not_raise(self) -> None:
        FakeEmbeddingService().health_check()

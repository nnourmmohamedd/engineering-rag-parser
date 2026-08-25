"""Core VectorRetriever behavior against a real, ephemeral Chroma collection."""

from __future__ import annotations

from typing import Any

import pytest

from engineering_rag.services.embedder.errors import EmptyQueryError
from engineering_rag.services.retriever.config import RetrievalSearchConfig
from engineering_rag.services.retriever.errors import (
    EmptyCollectionError,
    InvalidFilterError,
    MalformedChromaResponseError,
    RetrievalError,
)
from engineering_rag.services.retriever.models import RetrievalRequest
from engineering_rag.services.retriever.retriever import VectorRetriever

from .conftest import FixedVectorEmbedder


def _retriever(embedder: Any, collection: Any, **config_overrides: Any) -> VectorRetriever:
    config = RetrievalSearchConfig(
        allowed_metadata_filter_fields=["source_filename", "content_type"], **config_overrides
    )
    return VectorRetriever(
        embedder=embedder, collection=collection, config=config, collection_distance_metric="cosine"
    )


class TestQueryValidation:
    def test_empty_query_rejected(self, small_collection: Any, chunk_a_vector: list[float]) -> None:
        retriever = _retriever(FixedVectorEmbedder(chunk_a_vector), small_collection)
        with pytest.raises(RetrievalError):
            retriever.search(RetrievalRequest(query=""))

    def test_whitespace_only_query_rejected(self, small_collection: Any, chunk_a_vector: list[float]) -> None:
        retriever = _retriever(FixedVectorEmbedder(chunk_a_vector), small_collection)
        with pytest.raises(RetrievalError):
            retriever.search(RetrievalRequest(query="   \n\t  "))

    def test_query_over_max_length_rejected(self, small_collection: Any, chunk_a_vector: list[float]) -> None:
        retriever = _retriever(
            FixedVectorEmbedder(chunk_a_vector), small_collection, query_max_length_chars=10
        )
        with pytest.raises(RetrievalError, match="exceeds"):
            retriever.search(RetrievalRequest(query="this query is definitely longer than ten characters"))

    def test_top_k_over_maximum_rejected(self, small_collection: Any, chunk_a_vector: list[float]) -> None:
        retriever = _retriever(
            FixedVectorEmbedder(chunk_a_vector), small_collection, default_top_k=1, maximum_top_k=2
        )
        with pytest.raises(RetrievalError, match="exceeds"):
            retriever.search(RetrievalRequest(query="hello", top_k=5))

    def test_embedder_empty_query_error_becomes_retrieval_error(
        self, small_collection: Any, chunk_a_vector: list[float]
    ) -> None:
        class RaisingEmbedder(FixedVectorEmbedder):
            def embed_query(self, text: str) -> list[float]:
                raise EmptyQueryError("boom")

        retriever = _retriever(RaisingEmbedder(chunk_a_vector), small_collection)
        with pytest.raises(RetrievalError):
            retriever.search(RetrievalRequest(query="valid text"))


class TestQueryPrefixAppliedOnce:
    def test_prefix_applied_exactly_once(self, small_collection: Any, chunk_a_vector: list[float]) -> None:
        embedder = FixedVectorEmbedder(chunk_a_vector, query_prefix="Represent this sentence: ")
        retriever = _retriever(embedder, small_collection)
        retriever.search(RetrievalRequest(query="what is a P&ID?"))
        assert embedder.embedded_queries == ["Represent this sentence: what is a P&ID?"]
        assert embedder.embedded_queries[0].count("Represent this sentence: ") == 1


class TestEmptyAndMissingCollection:
    def test_empty_collection_raises(self, empty_collection: Any, chunk_a_vector: list[float]) -> None:
        retriever = _retriever(FixedVectorEmbedder(chunk_a_vector), empty_collection)
        with pytest.raises(EmptyCollectionError):
            retriever.search(RetrievalRequest(query="anything"))


class TestSearchResults:
    def test_returns_top_k_hits_with_provenance(
        self, small_collection: Any, chunk_a_vector: list[float]
    ) -> None:
        retriever = _retriever(FixedVectorEmbedder(chunk_a_vector), small_collection)
        response = retriever.search(RetrievalRequest(query="control systems", top_k=2))

        assert response.returned_count == 2
        assert response.requested_top_k == 2
        assert response.distance_metric == "cosine"
        top = response.hits[0]
        assert top.chunk_id == "chunk_a"
        assert top.raw_distance == pytest.approx(0.0, abs=1e-6)
        assert top.similarity_score == pytest.approx(1.0, abs=1e-6)
        assert top.source_filename == "a.pdf"
        assert top.page_numbers == [1]
        assert top.heading_path == ["Root", "Sub"]
        assert top.source_element_refs == ["#/texts/0"]
        assert top.content_hash == "hash_a"

    def test_rank_is_sequential_from_one(self, small_collection: Any, chunk_a_vector: list[float]) -> None:
        retriever = _retriever(FixedVectorEmbedder(chunk_a_vector), small_collection)
        response = retriever.search(RetrievalRequest(query="q", top_k=4))
        assert [h.rank for h in response.hits] == list(range(1, len(response.hits) + 1))

    def test_similarity_equals_one_minus_distance(
        self, small_collection: Any, chunk_a_vector: list[float]
    ) -> None:
        retriever = _retriever(FixedVectorEmbedder(chunk_a_vector), small_collection)
        response = retriever.search(RetrievalRequest(query="q", top_k=4))
        for hit in response.hits:
            assert hit.similarity_score == pytest.approx(1.0 - hit.raw_distance)

    def test_no_similarity_when_distance_metric_is_not_cosine(
        self, small_collection: Any, chunk_a_vector: list[float]
    ) -> None:
        config = RetrievalSearchConfig()
        retriever = VectorRetriever(
            embedder=FixedVectorEmbedder(chunk_a_vector),
            collection=small_collection,
            config=config,
            collection_distance_metric="l2",
        )
        response = retriever.search(RetrievalRequest(query="q", top_k=1))
        assert response.hits[0].similarity_score is None
        assert any("not computed" in w for w in response.warnings)


class TestMetadataFilters:
    def test_filter_narrows_results(self, small_collection: Any, chunk_a_vector: list[float]) -> None:
        retriever = _retriever(FixedVectorEmbedder(chunk_a_vector), small_collection)
        response = retriever.search(
            RetrievalRequest(query="q", top_k=10, metadata_filters={"source_filename": "b.pdf"})
        )
        assert {h.chunk_id for h in response.hits} == {"chunk_c"}

    def test_filter_matching_nothing_returns_empty_result(
        self, small_collection: Any, chunk_a_vector: list[float]
    ) -> None:
        retriever = _retriever(FixedVectorEmbedder(chunk_a_vector), small_collection)
        response = retriever.search(
            RetrievalRequest(query="q", top_k=10, metadata_filters={"source_filename": "nonexistent.pdf"})
        )
        assert response.hits == []
        assert response.returned_count == 0

    def test_invalid_filter_field_raises(self, small_collection: Any, chunk_a_vector: list[float]) -> None:
        retriever = _retriever(FixedVectorEmbedder(chunk_a_vector), small_collection)
        with pytest.raises(InvalidFilterError):
            retriever.search(RetrievalRequest(query="q", metadata_filters={"page_numbers": 1}))


class TestDiagnostics:
    def test_detects_duplicate_content_hash_without_dropping_either_record(
        self, small_collection: Any, chunk_a_vector: list[float]
    ) -> None:
        retriever = _retriever(FixedVectorEmbedder(chunk_a_vector), small_collection)
        response = retriever.search(RetrievalRequest(query="q", top_k=4))
        # chunk_a and chunk_d share content_hash="hash_a" by fixture construction.
        assert {"chunk_a", "chunk_d"} in [set(g) for g in response.diagnostics.duplicate_content_hashes]
        chunk_ids = [h.chunk_id for h in response.hits]
        assert "chunk_a" in chunk_ids
        assert "chunk_d" in chunk_ids

    def test_no_duplicates_reported_when_none_exist(
        self, small_collection: Any, chunk_a_vector: list[float]
    ) -> None:
        retriever = _retriever(FixedVectorEmbedder(chunk_a_vector), small_collection)
        response = retriever.search(
            RetrievalRequest(query="q", top_k=10, metadata_filters={"source_filename": "b.pdf"})
        )
        assert response.diagnostics.duplicate_content_hashes == []


class TestDeterministicOrderingAndSerialization:
    def test_repeated_calls_are_identical(self, small_collection: Any, chunk_a_vector: list[float]) -> None:
        retriever = _retriever(FixedVectorEmbedder(chunk_a_vector), small_collection)
        r1 = retriever.search(RetrievalRequest(query="q", top_k=4))
        r2 = retriever.search(RetrievalRequest(query="q", top_k=4))
        assert [h.chunk_id for h in r1.hits] == [h.chunk_id for h in r2.hits]

    def test_response_serializes_to_json(self, small_collection: Any, chunk_a_vector: list[float]) -> None:
        retriever = _retriever(FixedVectorEmbedder(chunk_a_vector), small_collection)
        response = retriever.search(RetrievalRequest(query="q", top_k=2))
        payload = response.model_dump(mode="json")
        assert payload["hits"][0]["chunk_id"] == "chunk_a"
        assert isinstance(payload["hits"][0]["raw_distance"], float)

    def test_search_does_not_mutate_collection_count(
        self, small_collection: Any, chunk_a_vector: list[float]
    ) -> None:
        retriever = _retriever(FixedVectorEmbedder(chunk_a_vector), small_collection)
        before = small_collection.count()
        retriever.search(RetrievalRequest(query="q", top_k=2))
        retriever.search(RetrievalRequest(query="q2", top_k=2))
        assert small_collection.count() == before


class TestMalformedChromaResponse:
    def test_mismatched_array_lengths_raise(self, small_collection: Any, chunk_a_vector: list[float]) -> None:
        class BrokenCollection:
            name = small_collection.name
            metadata = small_collection.metadata

            def count(self) -> int:
                return 4

            def query(self, **kwargs: Any) -> dict[str, Any]:
                return {
                    "ids": [["chunk_a", "chunk_b"]],
                    "documents": [["doc a"]],  # deliberately short
                    "metadatas": [[{}, {}]],
                    "distances": [[0.1, 0.2]],
                }

        retriever = _retriever(FixedVectorEmbedder(chunk_a_vector), BrokenCollection())
        with pytest.raises(MalformedChromaResponseError):
            retriever.search(RetrievalRequest(query="q"))

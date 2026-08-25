"""Data-contract tests: validation, JSON round-trip, query hashing."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from engineering_rag.services.retriever.models import (
    RetrievalEvaluationCase,
    RetrievalHit,
    RetrievalRequest,
    RetrievalResponse,
    query_hash,
)


class TestQueryHash:
    def test_stable_for_same_query(self) -> None:
        assert query_hash("hello world") == query_hash("hello world")

    def test_different_for_different_queries(self) -> None:
        assert query_hash("hello") != query_hash("world")

    def test_does_not_reveal_the_query(self) -> None:
        h = query_hash("a very specific secret-sounding query")
        assert "secret" not in h


class TestRetrievalRequest:
    def test_defaults(self) -> None:
        req = RetrievalRequest(query="what is a P&ID?")
        assert req.top_k == 5
        assert req.metadata_filters == {}

    def test_rejects_unknown_field(self) -> None:
        with pytest.raises(ValidationError):
            RetrievalRequest(query="x", bogus_field=1)  # type: ignore[call-arg]

    def test_rejects_non_positive_top_k(self) -> None:
        with pytest.raises(ValidationError):
            RetrievalRequest(query="x", top_k=0)


class TestRetrievalHitAndResponseSerialization:
    def test_hit_never_reprs_full_vector(self) -> None:
        hit = RetrievalHit(rank=1, chunk_id="c1", retrieval_text="text", raw_distance=0.1)
        assert "vector" not in repr(hit)

    def test_response_round_trips_through_json(self) -> None:
        hit = RetrievalHit(
            rank=1,
            chunk_id="c1",
            retrieval_text="the text",
            raw_distance=0.2,
            similarity_score=0.8,
            page_numbers=[1, 2],
            heading_path=["Section 1", "1.1"],
        )
        response = RetrievalResponse(
            query="q",
            query_hash=query_hash("q"),
            collection_name="col",
            requested_top_k=5,
            returned_count=1,
            embedding_model="m",
            embedding_revision=None,
            embedding_dimension=768,
            distance_metric="cosine",
            embedding_duration_s=0.01,
            database_duration_s=0.01,
            total_duration_s=0.02,
            hits=[hit],
        )
        payload = json.loads(response.model_dump_json())
        restored = RetrievalResponse.model_validate(payload)
        assert restored == response
        assert restored.hits[0].page_numbers == [1, 2]

    def test_response_forbids_unknown_top_level_field(self) -> None:
        with pytest.raises(ValidationError):
            RetrievalResponse.model_validate(
                {
                    "query": "q",
                    "query_hash": "h",
                    "collection_name": "c",
                    "requested_top_k": 1,
                    "returned_count": 0,
                    "embedding_model": "m",
                    "embedding_revision": None,
                    "embedding_dimension": 768,
                    "distance_metric": "cosine",
                    "embedding_duration_s": 0.0,
                    "database_duration_s": 0.0,
                    "total_duration_s": 0.0,
                    "unexpected": True,
                }
            )


class TestRetrievalEvaluationCase:
    def test_unanswerable_case_defaults_have_no_relevant_ids(self) -> None:
        case = RetrievalEvaluationCase(
            case_id="c1",
            query="unanswerable question",
            query_type="negative",
            source_document="doc.pdf",
            is_unanswerable=True,
        )
        assert case.relevant_chunk_ids == []

    def test_rejects_unknown_query_type(self) -> None:
        with pytest.raises(ValidationError):
            RetrievalEvaluationCase(
                case_id="c1",
                query="q",
                query_type="not_a_real_type",  # type: ignore[arg-type]
                source_document="doc.pdf",
            )

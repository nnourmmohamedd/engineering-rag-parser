"""Evaluation-runner tests: per-case scoring and aggregate summary construction."""

from __future__ import annotations

from typing import Any

from engineering_rag.services.retriever.config import RetrievalSearchConfig
from engineering_rag.services.retriever.evaluation.runner import evaluate_case, run_evaluation
from engineering_rag.services.retriever.models import RetrievalEvaluationCase
from engineering_rag.services.retriever.retriever import VectorRetriever

from ..conftest import FixedVectorEmbedder  # noqa: TID252 - sibling test conftest, not runtime code


def _retriever(collection: Any, vector: list[float]) -> VectorRetriever:
    config = RetrievalSearchConfig(allowed_metadata_filter_fields=["source_filename", "content_type"])
    return VectorRetriever(
        embedder=FixedVectorEmbedder(vector),
        collection=collection,
        config=config,
        collection_distance_metric="cosine",
    )


class TestEvaluateCase:
    def test_positive_case_scores_correctly(self, small_collection: Any, chunk_a_vector: list[float]) -> None:
        retriever = _retriever(small_collection, chunk_a_vector)
        case = RetrievalEvaluationCase(
            case_id="c1",
            query="control systems",
            query_type="exact_term",
            source_document="a.pdf",
            relevant_chunk_ids=["chunk_a"],
        )
        result = evaluate_case(retriever, case, k_values=[1, 3], unanswerable_similarity_threshold=0.5)
        assert result.hit_rate_at_k[1] == 1.0
        assert result.reciprocal_rank == 1.0
        assert result.retrieved_chunk_ids[0] == "chunk_a"

    def test_unanswerable_case_uses_no_result_correct(
        self, small_collection: Any, chunk_a_vector: list[float]
    ) -> None:
        low_norm_vector = [
            -x for x in chunk_a_vector
        ]  # near-opposite direction -> low similarity to everything
        retriever = _retriever(small_collection, low_norm_vector)
        case = RetrievalEvaluationCase(
            case_id="c1",
            query="totally unrelated topic",
            query_type="negative",
            source_document="a.pdf",
            is_unanswerable=True,
        )
        result = evaluate_case(retriever, case, k_values=[1], unanswerable_similarity_threshold=0.9)
        assert result.no_result_correct is True
        assert result.hit_rate_at_k == {}

    def test_positive_case_without_relevant_ids_warns(
        self, small_collection: Any, chunk_a_vector: list[float]
    ) -> None:
        retriever = _retriever(small_collection, chunk_a_vector)
        case = RetrievalEvaluationCase(
            case_id="c1", query="q", query_type="exact_term", source_document="a.pdf", relevant_chunk_ids=[]
        )
        result = evaluate_case(retriever, case, k_values=[1], unanswerable_similarity_threshold=0.5)
        assert any("not marked is_unanswerable" in w for w in result.warnings)
        assert result.hit_rate_at_k[1] == 0.0


class TestRunEvaluation:
    def test_aggregates_positive_and_negative_separately(
        self, small_collection: Any, chunk_a_vector: list[float]
    ) -> None:
        retriever = _retriever(small_collection, chunk_a_vector)
        cases = [
            RetrievalEvaluationCase(
                case_id="pos",
                query="control systems",
                query_type="exact_term",
                source_document="a.pdf",
                relevant_chunk_ids=["chunk_a"],
            ),
            RetrievalEvaluationCase(
                case_id="neg",
                query="unrelated",
                query_type="negative",
                source_document="a.pdf",
                is_unanswerable=True,
            ),
        ]
        results, summary = run_evaluation(
            retriever,
            cases,
            run_id="test-run",
            dataset_path="fake.jsonl",
            dataset_hash="deadbeef",
            dataset_version="2",
            k_values=[1, 3],
            unanswerable_similarity_threshold=0.5,
            collection_name=small_collection.name,
            collection_count=small_collection.count(),
            distance_metric="cosine",
            embedding_model="fixed-test-embedder",
            embedding_revision="test",
            reproduction_command="engrag-retrieve evaluate",
        )
        assert summary.case_count == 2
        assert summary.positive_case_count == 1
        assert summary.negative_case_count == 1
        assert summary.hit_rate_at_k[1] == 1.0  # only the positive case contributes
        assert len(results) == 2
        assert summary.human_reviewed_count == 0  # both default to machine_candidate

    def test_limitations_flag_unreviewed_cases(
        self, small_collection: Any, chunk_a_vector: list[float]
    ) -> None:
        retriever = _retriever(small_collection, chunk_a_vector)
        cases = [
            RetrievalEvaluationCase(
                case_id="c1",
                query="q",
                query_type="exact_term",
                source_document="a.pdf",
                relevant_chunk_ids=["chunk_a"],
                human_review_status="machine_candidate",
            )
        ]
        _results, summary = run_evaluation(
            retriever,
            cases,
            run_id="r",
            dataset_path="f.jsonl",
            dataset_hash="h",
            dataset_version="1",
            k_values=[1],
            unanswerable_similarity_threshold=0.5,
            collection_name=small_collection.name,
            collection_count=small_collection.count(),
            distance_metric="cosine",
            embedding_model="m",
            embedding_revision=None,
            reproduction_command="cmd",
        )
        assert any("machine_candidate" in item for item in summary.limitations)

    def test_no_result_accuracy_is_none_with_no_negative_cases(
        self, small_collection: Any, chunk_a_vector: list[float]
    ) -> None:
        retriever = _retriever(small_collection, chunk_a_vector)
        cases = [
            RetrievalEvaluationCase(
                case_id="c1",
                query="q",
                query_type="exact_term",
                source_document="a.pdf",
                relevant_chunk_ids=["chunk_a"],
            )
        ]
        _results, summary = run_evaluation(
            retriever,
            cases,
            run_id="r",
            dataset_path="f.jsonl",
            dataset_hash="h",
            dataset_version="1",
            k_values=[1],
            unanswerable_similarity_threshold=0.5,
            collection_name=small_collection.name,
            collection_count=small_collection.count(),
            distance_metric="cosine",
            embedding_model="m",
            embedding_revision=None,
            reproduction_command="cmd",
        )
        assert summary.no_result_accuracy is None

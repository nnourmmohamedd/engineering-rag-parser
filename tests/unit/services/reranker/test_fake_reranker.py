from __future__ import annotations

from engineering_rag.services.reranker.models import RerankCandidate
from tests.support.fake_reranker import FakeReranker


class TestFakeReranker:
    def test_empty_candidates_returns_empty_without_recording_a_real_call(self) -> None:
        reranker = FakeReranker()
        assert reranker.rerank("query", []) == []

    def test_ranks_by_term_overlap(self) -> None:
        reranker = FakeReranker()
        candidates = [
            RerankCandidate(chunk_id="a", text="totally unrelated content"),
            RerankCandidate(chunk_id="b", text="control valve regulates flow"),
        ]
        results = reranker.rerank("control valve", candidates)
        assert results[0].chunk_id == "b"
        assert results[0].rank == 1
        assert results[1].chunk_id == "a"

    def test_deterministic_tie_break_by_chunk_id(self) -> None:
        reranker = FakeReranker()
        candidates = [
            RerankCandidate(chunk_id="z", text="same same"),
            RerankCandidate(chunk_id="a", text="same same"),
        ]
        results = reranker.rerank("same", candidates)
        assert [r.chunk_id for r in results] == ["a", "z"]

    def test_result_count_matches_candidate_count(self) -> None:
        reranker = FakeReranker()
        candidates = [RerankCandidate(chunk_id=str(i), text=f"text {i}") for i in range(5)]
        results = reranker.rerank("text", candidates)
        assert len(results) == 5

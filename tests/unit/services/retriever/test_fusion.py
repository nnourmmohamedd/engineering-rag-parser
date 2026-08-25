from __future__ import annotations

from engineering_rag.services.retriever.fusion import reciprocal_rank_fusion
from engineering_rag.services.retriever.models import RetrievalHit


def _hit(chunk_id: str, rank: int, distance: float = 0.1) -> RetrievalHit:
    return RetrievalHit(
        rank=rank, chunk_id=chunk_id, retrieval_text=f"text-{chunk_id}", raw_distance=distance
    )


class TestReciprocalRankFusion:
    def test_exact_scores_both_lists(self) -> None:
        vector_hits = [_hit("a", 1), _hit("b", 2)]
        bm25_hits = [_hit("b", 1), _hit("a", 2)]
        fused = reciprocal_rank_fusion(vector_hits, bm25_hits, rrf_k=60)
        scores = {f.chunk_id: f.rrf_score for f in fused}
        expected_a = 1 / (60 + 1) + 1 / (60 + 2)
        expected_b = 1 / (60 + 2) + 1 / (60 + 1)
        assert scores["a"] == expected_a
        assert scores["b"] == expected_b
        assert scores["a"] == scores["b"]  # symmetric ranks -> tied score

    def test_candidate_only_in_one_list(self) -> None:
        vector_hits = [_hit("only_vector", 1)]
        bm25_hits: list[RetrievalHit] = []
        fused = reciprocal_rank_fusion(vector_hits, bm25_hits, rrf_k=60)
        assert len(fused) == 1
        assert fused[0].rrf_score == 1 / (60 + 1)
        assert fused[0].vector_rank == 1
        assert fused[0].bm25_rank is None

    def test_deduplicates_by_chunk_id(self) -> None:
        vector_hits = [_hit("a", 1), _hit("b", 2)]
        bm25_hits = [_hit("a", 1)]
        fused = reciprocal_rank_fusion(vector_hits, bm25_hits, rrf_k=60)
        ids = [f.chunk_id for f in fused]
        assert sorted(ids) == ["a", "b"]

    def test_deterministic_tie_break_by_chunk_id(self) -> None:
        vector_hits = [_hit("z", 1), _hit("a", 2)]
        bm25_hits = [_hit("a", 1), _hit("z", 2)]
        fused = reciprocal_rank_fusion(vector_hits, bm25_hits, rrf_k=60)
        # both "z" and "a" get identical combined scores (1/61 + 1/62 either way);
        # tie-break must be deterministic ascending chunk_id
        assert [f.chunk_id for f in fused] == ["a", "z"]

    def test_different_list_lengths(self) -> None:
        vector_hits = [_hit(f"v{i}", i) for i in range(1, 11)]
        bm25_hits = [_hit("v1", 1)]
        fused = reciprocal_rank_fusion(vector_hits, bm25_hits, rrf_k=60)
        assert len(fused) == 10
        top = next(f for f in fused if f.chunk_id == "v1")
        assert top.vector_rank == 1
        assert top.bm25_rank == 1

    def test_configurable_rrf_k(self) -> None:
        vector_hits = [_hit("a", 1)]
        fused_small_k = reciprocal_rank_fusion(vector_hits, [], rrf_k=1)
        fused_large_k = reciprocal_rank_fusion(vector_hits, [], rrf_k=1000)
        assert fused_small_k[0].rrf_score > fused_large_k[0].rrf_score

    def test_never_mixes_raw_scores(self) -> None:
        # A hit with a very strong cosine similarity but a low BM25 score must not have its
        # rrf_score influenced by the magnitude of similarity_score or bm25_score directly —
        # only rank position matters.
        vector_hits = [_hit("a", 1).model_copy(update={"similarity_score": 0.99})]
        bm25_hits = [_hit("a", 1).model_copy(update={"bm25_score": 1e6})]
        fused = reciprocal_rank_fusion(vector_hits, bm25_hits, rrf_k=60)
        assert fused[0].rrf_score == 2 / 61

    def test_output_hits_carry_rrf_rank_and_score(self) -> None:
        vector_hits = [_hit("a", 1), _hit("b", 2)]
        bm25_hits = [_hit("b", 1), _hit("a", 2)]
        fused = reciprocal_rank_fusion(vector_hits, bm25_hits, rrf_k=60)
        assert fused[0].hit.rrf_rank == 1
        assert fused[0].hit.rrf_score == fused[0].rrf_score
        assert fused[1].hit.rrf_rank == 2

    def test_empty_both_lists(self) -> None:
        assert reciprocal_rank_fusion([], [], rrf_k=60) == []

"""Metric calculation tests: closed-form checks against hand-computed expected values."""

from __future__ import annotations

import math

import pytest

from engineering_rag.services.retriever.evaluation.metrics import (
    hit_rate_at_k,
    ndcg_at_k,
    no_result_correct,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


class TestHitRateAtK:
    def test_hit_within_k(self) -> None:
        assert hit_rate_at_k(["a", "b", "c"], {"c"}, 3) == 1.0

    def test_miss_within_k(self) -> None:
        assert hit_rate_at_k(["a", "b", "c"], {"z"}, 2) == 0.0

    def test_relevant_beyond_k_is_a_miss(self) -> None:
        assert hit_rate_at_k(["a", "b", "c"], {"c"}, 2) == 0.0

    def test_no_relevant_ids_is_zero(self) -> None:
        assert hit_rate_at_k(["a", "b"], set(), 5) == 0.0


class TestRecallAtK:
    def test_full_recall(self) -> None:
        assert recall_at_k(["a", "b"], {"a", "b"}, 2) == 1.0

    def test_partial_recall(self) -> None:
        assert recall_at_k(["a", "x"], {"a", "b"}, 2) == 0.5

    def test_zero_recall_no_relevant(self) -> None:
        assert recall_at_k(["a"], set(), 1) == 0.0


class TestPrecisionAtK:
    def test_all_relevant(self) -> None:
        assert precision_at_k(["a", "b"], {"a", "b"}, 2) == 1.0

    def test_half_relevant(self) -> None:
        assert precision_at_k(["a", "x"], {"a"}, 2) == 0.5

    def test_denominator_is_k_not_len_retrieved(self) -> None:
        # Only 1 result returned but k=4 requested: precision divides by k=4, not 1.
        assert precision_at_k(["a"], {"a"}, 4) == 0.25

    def test_zero_k_is_zero(self) -> None:
        assert precision_at_k(["a"], {"a"}, 0) == 0.0


class TestReciprocalRank:
    def test_first_position(self) -> None:
        assert reciprocal_rank(["a", "b"], {"a"}) == 1.0

    def test_second_position(self) -> None:
        assert reciprocal_rank(["a", "b"], {"b"}) == 0.5

    def test_not_found(self) -> None:
        assert reciprocal_rank(["a", "b"], {"z"}) == 0.0

    def test_first_relevant_wins_with_multiple_relevant(self) -> None:
        assert reciprocal_rank(["a", "b", "c"], {"b", "c"}) == 0.5


class TestNdcgAtK:
    def test_perfect_ranking_is_one(self) -> None:
        assert ndcg_at_k(["a", "b"], {"a", "b"}, 2) == pytest.approx(1.0)

    def test_reversed_ranking_is_less_than_one(self) -> None:
        # relevant={"b"} only, but it's ranked second instead of first.
        score = ndcg_at_k(["a", "b"], {"b"}, 2)
        assert 0.0 < score < 1.0
        assert score == pytest.approx(1.0 / math.log2(3))

    def test_no_relevant_is_zero(self) -> None:
        assert ndcg_at_k(["a", "b"], set(), 2) == 0.0

    def test_no_hits_is_zero(self) -> None:
        assert ndcg_at_k(["a", "b"], {"z"}, 2) == 0.0


class TestNoResultCorrect:
    def test_below_threshold_is_correct(self) -> None:
        assert no_result_correct(0.2, threshold=0.5) is True

    def test_above_threshold_is_incorrect(self) -> None:
        assert no_result_correct(0.9, threshold=0.5) is False

    def test_none_similarity_is_unjudged(self) -> None:
        assert no_result_correct(None, threshold=0.5) is None

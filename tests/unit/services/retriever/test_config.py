"""Configuration validation tests for the retrieval search/evaluation profiles."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from engineering_rag.services.retriever.config import RetrievalEvaluationConfig, RetrievalSearchConfig


class TestRetrievalSearchConfig:
    def test_defaults_are_valid(self) -> None:
        config = RetrievalSearchConfig()
        assert config.default_top_k <= config.maximum_top_k

    def test_rejects_default_top_k_above_maximum(self) -> None:
        with pytest.raises(ValidationError):
            RetrievalSearchConfig(default_top_k=100, maximum_top_k=10)

    def test_rejects_unknown_field(self) -> None:
        with pytest.raises(ValidationError):
            RetrievalSearchConfig(bogus=1)  # type: ignore[call-arg]

    def test_is_frozen(self) -> None:
        config = RetrievalSearchConfig()
        with pytest.raises(ValidationError):
            config.default_top_k = 99  # type: ignore[misc]

    def test_effective_dict_is_json_safe(self) -> None:
        config = RetrievalSearchConfig()
        assert config.effective_dict()["default_top_k"] == config.default_top_k


class TestRetrievalEvaluationConfig:
    def test_defaults_are_valid(self) -> None:
        config = RetrievalEvaluationConfig()
        assert config.k_values == [1, 3, 5, 10]

    def test_rejects_empty_k_values(self) -> None:
        with pytest.raises(ValidationError):
            RetrievalEvaluationConfig(k_values=[])

    def test_rejects_non_positive_k(self) -> None:
        with pytest.raises(ValidationError):
            RetrievalEvaluationConfig(k_values=[0, 1])

    def test_rejects_duplicate_k_values(self) -> None:
        with pytest.raises(ValidationError):
            RetrievalEvaluationConfig(k_values=[1, 1, 3])

    def test_rejects_threshold_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            RetrievalEvaluationConfig(unanswerable_similarity_threshold=1.5)

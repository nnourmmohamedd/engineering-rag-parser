from __future__ import annotations

import pytest
from pydantic import ValidationError

from engineering_rag.services.reranker.config import RerankerConfig


class TestRerankerConfig:
    def test_defaults_disabled(self) -> None:
        cfg = RerankerConfig()
        assert cfg.enabled is False
        assert cfg.model_name == "BAAI/bge-reranker-base"

    def test_candidate_top_k_must_be_at_least_final_top_k(self) -> None:
        with pytest.raises(ValidationError, match="candidate_top_k"):
            RerankerConfig(candidate_top_k=3, final_top_k=5)

    def test_candidate_top_k_equal_to_final_top_k_is_valid(self) -> None:
        cfg = RerankerConfig(candidate_top_k=5, final_top_k=5)
        assert cfg.candidate_top_k == cfg.final_top_k

    @pytest.mark.parametrize("field", ["candidate_top_k", "final_top_k", "batch_size", "max_length"])
    def test_positive_fields(self, field: str) -> None:
        with pytest.raises(ValidationError):
            RerankerConfig(**{field: 0})

    def test_unknown_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RerankerConfig(bogus=True)

from __future__ import annotations

import pytest
from pydantic import ValidationError

from engineering_rag.services.retriever.config import FusionConfig, RetrievalModeConfig


class TestRetrievalModeConfig:
    def test_defaults_are_vector_only(self) -> None:
        cfg = RetrievalModeConfig()
        assert cfg.vector_enabled is True
        assert cfg.bm25_enabled is False

    def test_vector_enabled_false_rejected(self) -> None:
        with pytest.raises(ValidationError, match="vector_enabled must remain true"):
            RetrievalModeConfig(vector_enabled=False)

    @pytest.mark.parametrize("field", ["vector_top_k", "bm25_top_k", "final_top_k"])
    def test_top_k_fields_must_be_positive(self, field: str) -> None:
        with pytest.raises(ValidationError):
            RetrievalModeConfig(**{field: 0})

    def test_unknown_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RetrievalModeConfig(made_up_field=True)


class TestFusionConfig:
    def test_defaults(self) -> None:
        cfg = FusionConfig()
        assert cfg.method == "rrf"
        assert cfg.rrf_k == 60

    def test_rrf_k_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            FusionConfig(rrf_k=0)

    def test_invalid_method_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FusionConfig(method="not-rrf")

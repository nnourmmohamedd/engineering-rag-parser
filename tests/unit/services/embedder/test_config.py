"""EmbedderConfig validation tests."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from engineering_rag.services.embedder.config import DEFAULT_QUERY_PREFIX, EmbedderConfig


class TestEmbedderConfig:
    def test_defaults_are_valid(self) -> None:
        cfg = EmbedderConfig()
        assert cfg.model_name == "BAAI/bge-base-en-v1.5"
        assert cfg.expected_dimension == 768
        assert cfg.normalize_embeddings is True
        assert cfg.query_prefix == DEFAULT_QUERY_PREFIX

    def test_config_is_frozen(self) -> None:
        cfg = EmbedderConfig()
        with pytest.raises(ValidationError):
            cfg.batch_size = 999  # type: ignore[misc]

    def test_unknown_key_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EmbedderConfig.model_validate({"not_a_real_key": 1})

    def test_batch_size_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            EmbedderConfig.model_validate({"batch_size": 0})

    def test_expected_dimension_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            EmbedderConfig.model_validate({"expected_dimension": 0})

    def test_empty_model_name_rejected(self) -> None:
        with pytest.raises(ValidationError, match="model_name"):
            EmbedderConfig.model_validate({"model_name": "   "})

    def test_empty_query_prefix_rejected(self) -> None:
        with pytest.raises(ValidationError, match="query_prefix"):
            EmbedderConfig.model_validate({"query_prefix": "   "})

    def test_invalid_device_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EmbedderConfig.model_validate({"device": "tpu"})

    def test_config_hash_stable_and_sensitive(self) -> None:
        a = EmbedderConfig()
        b = EmbedderConfig()
        assert a.config_hash() == b.config_hash()
        c = a.with_overrides(batch_size=64)
        assert a.config_hash() != c.config_hash()

    def test_effective_dict_json_serialisable(self) -> None:
        json.dumps(EmbedderConfig().effective_dict(), default=str)

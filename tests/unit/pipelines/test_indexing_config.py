"""IndexingConfig composition + validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from engineering_rag.pipelines.indexing_config import IndexingConfig, load_indexing_config


class TestIndexingConfig:
    def test_defaults_are_valid(self) -> None:
        cfg = IndexingConfig()
        assert cfg.embedding.expected_dimension == 768
        assert cfg.chroma.distance_metric == "cosine"

    def test_frozen(self) -> None:
        cfg = IndexingConfig()
        with pytest.raises(ValidationError):
            cfg.strict = True  # type: ignore[misc]

    def test_unknown_top_level_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IndexingConfig.model_validate({"bogus": 1})

    def test_dimension_must_be_768(self) -> None:
        with pytest.raises(ValidationError, match="768"):
            IndexingConfig.model_validate({"embedding": {"expected_dimension": 384}})

    def test_nested_unknown_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IndexingConfig.model_validate({"chroma": {"bogus_field": 1}})

    def test_config_hash_stable_and_sensitive(self) -> None:
        a = IndexingConfig()
        b = IndexingConfig()
        assert a.config_hash() == b.config_hash()
        c = IndexingConfig.model_validate({"strict": True})
        assert a.config_hash() != c.config_hash()


class TestLoadIndexingConfig:
    def test_real_production_profile_loads(self) -> None:
        cfg = load_indexing_config("configs/indexing_production.yaml")
        assert cfg.embedding.model_name == "BAAI/bge-base-en-v1.5"
        assert cfg.chroma.collection_name == "engineering_documents_v1"

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_indexing_config("does/not/exist.yaml")

    def test_none_path_yields_defaults(self) -> None:
        cfg = load_indexing_config(None)
        assert cfg == IndexingConfig()

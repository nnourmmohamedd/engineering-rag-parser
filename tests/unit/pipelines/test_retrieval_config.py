"""Top-level retrieval configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from engineering_rag.pipelines.retrieval_config import RetrievalConfig, load_retrieval_config


class TestLoadRetrievalConfig:
    def test_defaults_load(self) -> None:
        config = load_retrieval_config()
        assert config.embedding.expected_dimension == 768
        assert config.chroma.distance_metric == "cosine"

    def test_shipped_production_profile_loads(self) -> None:
        config = load_retrieval_config(Path("configs/retrieval_production.yaml"))
        assert config.embedding.model_name == "BAAI/bge-base-en-v1.5"
        assert config.search.default_top_k == 5
        assert config.evaluation.k_values == [1, 3, 5, 10]

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_retrieval_config(tmp_path / "missing.yaml")

    def test_non_mapping_yaml_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(ValueError, match="YAML mapping"):
            load_retrieval_config(path)

    def test_unknown_top_level_key_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text(yaml.safe_dump({"bogus_section": {}}), encoding="utf-8")
        with pytest.raises(ValidationError):
            load_retrieval_config(path)

    def test_config_hash_is_stable_and_sensitive_to_changes(self) -> None:
        config1 = RetrievalConfig()
        config2 = RetrievalConfig()
        assert config1.config_hash() == config2.config_hash()
        config3 = config1.model_copy(
            update={"search": config1.search.model_copy(update={"default_top_k": 9})}
        )
        assert config3.config_hash() != config1.config_hash()

    def test_overrides_applied(self) -> None:
        config = load_retrieval_config(Path("configs/retrieval_production.yaml"), profile="production")
        assert config.profile == "production"

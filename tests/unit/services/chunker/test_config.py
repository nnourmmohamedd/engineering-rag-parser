"""Configuration validation tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from engineering_rag.services.chunker.config import ChunkerConfig, load_config


class TestChunkerConfig:
    def test_defaults_are_valid(self) -> None:
        cfg = ChunkerConfig()
        assert cfg.max_tokens == 256
        assert cfg.tokenizer.name == "sentence-transformers/all-MiniLM-L6-v2"

    def test_config_hash_is_stable(self) -> None:
        assert ChunkerConfig().config_hash() == ChunkerConfig().config_hash()

    def test_config_hash_changes_with_content(self) -> None:
        a = ChunkerConfig()
        b = a.with_overrides(max_tokens=300)
        assert a.config_hash() != b.config_hash()

    def test_config_is_frozen(self) -> None:
        cfg = ChunkerConfig()
        with pytest.raises(ValidationError):
            cfg.max_tokens = 999  # type: ignore[misc]

    def test_unknown_key_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChunkerConfig.model_validate({"not_a_real_key": 1})

    def test_min_chunk_tokens_must_be_below_max_tokens(self) -> None:
        with pytest.raises(ValidationError, match="min_chunk_tokens"):
            ChunkerConfig.model_validate({"min_chunk_tokens": 300, "max_tokens": 256})

    def test_target_tokens_must_not_exceed_max_tokens(self) -> None:
        with pytest.raises(ValidationError, match="target_tokens"):
            ChunkerConfig.model_validate({"target_tokens": 300, "max_tokens": 256})

    def test_overlap_must_be_below_target(self) -> None:
        with pytest.raises(ValidationError, match="text_overlap_tokens"):
            ChunkerConfig.model_validate({"text_overlap_tokens": 200, "target_tokens": 180})

    def test_separators_must_end_with_empty_fallback(self) -> None:
        with pytest.raises(ValidationError, match="recursive_separators"):
            ChunkerConfig.model_validate({"recursive_separators": ["\n\n", "\n"]})

    def test_effective_dict_is_json_serialisable(self) -> None:
        import json

        json.dumps(ChunkerConfig().effective_dict(), default=str)


class TestLoadConfig:
    def test_none_path_yields_defaults(self) -> None:
        assert load_config(None).config_hash() == ChunkerConfig().config_hash()

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nope.yaml")

    def test_non_mapping_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(ValueError, match="YAML mapping"):
            load_config(path)

    def test_shipped_production_profile_loads(self) -> None:
        path = Path("configs/chunker_production.yaml")
        if not path.is_file():
            pytest.skip(f"{path} not present")
        cfg = load_config(path)
        assert cfg.profile == "production"
        assert cfg.config_hash()

    def test_overrides_apply(self, tmp_path: Path) -> None:
        path = tmp_path / "c.yaml"
        path.write_text(yaml.safe_dump({"max_tokens": 256}), encoding="utf-8")
        assert load_config(path, strict=True).strict is True

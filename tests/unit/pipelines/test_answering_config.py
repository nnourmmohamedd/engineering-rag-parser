from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from engineering_rag.pipelines.answering_config import AnsweringPipelineConfig, load_answering_config


class TestBudgetValidation:
    def test_default_config_fits_budget(self) -> None:
        config = AnsweringPipelineConfig()
        assert config.ollama.context_window_tokens >= (
            config.context_builder.max_context_tokens
            + config.context_builder.reserved_system_tokens
            + config.context_builder.safety_margin_tokens
            + config.ollama.max_output_tokens
        )

    def test_oversized_budget_rejected(self) -> None:
        with pytest.raises(ValueError, match="Token budget does not fit"):
            AnsweringPipelineConfig(
                context_builder={"max_context_tokens": 100_000},
                ollama={"context_window_tokens": 8192},
            )

    def test_think_true_rejected_even_nested_in_pipeline_config(self) -> None:
        with pytest.raises(ValueError, match="think"):
            AnsweringPipelineConfig(ollama={"think": True})


class TestLoadAnsweringConfig:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_answering_config(tmp_path / "missing.yaml")

    def test_non_mapping_yaml_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "profile.yaml"
        path.write_text(yaml.safe_dump([1, 2, 3]), encoding="utf-8")
        with pytest.raises(ValueError, match="mapping"):
            load_answering_config(path)

    def test_unknown_key_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "profile.yaml"
        path.write_text(yaml.safe_dump({"not_a_real_section": {}}), encoding="utf-8")
        with pytest.raises(Exception, match="not_a_real_section"):
            load_answering_config(path)

    def test_real_production_profile_loads(self) -> None:
        config = load_answering_config(Path("configs/answering_production.yaml"))
        assert config.ollama.model == "qwen3:4b"
        assert config.ollama.think is False
        assert config.answering.prompt_version == "1.0.0"

    def test_config_hash_is_stable(self) -> None:
        config = AnsweringPipelineConfig()
        assert config.config_hash() == config.config_hash()

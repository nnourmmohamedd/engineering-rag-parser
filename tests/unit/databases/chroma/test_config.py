"""ChromaConfig and collection-name validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from engineering_rag.databases.chroma.config import ChromaConfig, validate_collection_name


class TestChromaConfig:
    def test_defaults_are_valid(self) -> None:
        cfg = ChromaConfig()
        assert cfg.collection_name == "engineering_documents_v1"
        assert cfg.distance_metric == "cosine"

    def test_config_is_frozen(self) -> None:
        cfg = ChromaConfig()
        with pytest.raises(ValidationError):
            cfg.collection_name = "x"  # type: ignore[misc]

    def test_unknown_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChromaConfig.model_validate({"bogus": 1})

    def test_invalid_metric_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChromaConfig.model_validate({"distance_metric": "euclidean"})

    def test_non_positive_batch_size_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChromaConfig.model_validate({"ingestion_batch_size": 0})

    def test_invalid_collection_name_rejected_at_parse_time(self) -> None:
        with pytest.raises(ValidationError, match="collection_name"):
            ChromaConfig.model_validate({"collection_name": "ab"})


class TestValidateCollectionName:
    @pytest.mark.parametrize("name", ["abc", "valid_name-1", "a.b.c", "engineering_documents_v1"])
    def test_valid_names_pass(self, name: str) -> None:
        validate_collection_name(name)

    def test_too_short_rejected(self) -> None:
        with pytest.raises(ValueError, match="3-512"):
            validate_collection_name("ab")

    def test_starts_with_non_alnum_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_collection_name("_abc")

    def test_ends_with_non_alnum_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_collection_name("abc_")

    def test_illegal_character_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_collection_name("abc def")

    def test_consecutive_periods_rejected(self) -> None:
        with pytest.raises(ValueError, match="consecutive periods"):
            validate_collection_name("a..b")

    def test_ipv4_address_rejected(self) -> None:
        with pytest.raises(ValueError, match="IPv4"):
            validate_collection_name("1.2.3.4")

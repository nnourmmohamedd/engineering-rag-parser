"""Chroma-safe metadata serialization tests."""

from __future__ import annotations

import json

from engineering_rag.databases.chroma.metadata import chroma_safe_metadata


class TestChromaSafeMetadata:
    def test_scalars_pass_through(self) -> None:
        result = chroma_safe_metadata({"a": 1, "b": "text", "c": 1.5, "d": True})
        assert result == {"a": 1, "b": "text", "c": 1.5, "d": True}

    def test_none_values_omitted(self) -> None:
        result = chroma_safe_metadata({"a": 1, "b": None})
        assert "b" not in result
        assert result == {"a": 1}

    def test_empty_list_omitted(self) -> None:
        result = chroma_safe_metadata({"a": []})
        assert "a" not in result

    def test_empty_dict_omitted(self) -> None:
        result = chroma_safe_metadata({"a": {}})
        assert "a" not in result

    def test_list_is_json_encoded_string(self) -> None:
        result = chroma_safe_metadata({"heading_path": ["Section 1", "1.1"]})
        assert isinstance(result["heading_path"], str)
        assert json.loads(result["heading_path"]) == ["Section 1", "1.1"]

    def test_dict_is_json_encoded_string(self) -> None:
        result = chroma_safe_metadata({"table_metadata": {"num_rows": 3}})
        assert isinstance(result["table_metadata"], str)
        assert json.loads(result["table_metadata"]) == {"num_rows": 3}

    def test_no_none_values_in_output(self) -> None:
        result = chroma_safe_metadata({"a": 1, "b": None, "c": None, "d": "x"})
        assert None not in result.values()

    def test_all_values_are_chroma_legal_types(self) -> None:
        result = chroma_safe_metadata({"a": 1, "b": "x", "c": 1.1, "d": True, "e": [1, 2], "f": None})
        for v in result.values():
            assert isinstance(v, str | int | float | bool)

    def test_oversized_value_is_truncated(self) -> None:
        big_list = list(range(5000))
        result = chroma_safe_metadata({"huge": big_list})
        assert len(result["huge"]) <= 4000
        assert result["huge"].endswith('...(truncated)"')

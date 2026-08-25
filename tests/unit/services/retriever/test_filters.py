"""Metadata filter validation and Chroma ``where`` clause construction."""

from __future__ import annotations

import pytest

from engineering_rag.services.retriever.config import RetrievalSearchConfig
from engineering_rag.services.retriever.errors import InvalidFilterError
from engineering_rag.services.retriever.filters import build_where_clause


@pytest.fixture
def config() -> RetrievalSearchConfig:
    return RetrievalSearchConfig(allowed_metadata_filter_fields=["source_filename", "content_type"])


class TestBuildWhereClause:
    def test_empty_filters_returns_none(self, config: RetrievalSearchConfig) -> None:
        assert build_where_clause({}, config) is None

    def test_single_field(self, config: RetrievalSearchConfig) -> None:
        assert build_where_clause({"source_filename": "a.pdf"}, config) == {"source_filename": "a.pdf"}

    def test_multiple_fields_are_anded(self, config: RetrievalSearchConfig) -> None:
        where = build_where_clause({"source_filename": "a.pdf", "content_type": "table"}, config)
        assert where == {"$and": [{"content_type": "table"}, {"source_filename": "a.pdf"}]}

    def test_rejects_disallowed_field(self, config: RetrievalSearchConfig) -> None:
        with pytest.raises(InvalidFilterError, match="unsupported metadata filter field"):
            build_where_clause({"page_numbers": 5}, config)

    def test_rejects_unsupported_value_type(self, config: RetrievalSearchConfig) -> None:
        with pytest.raises(InvalidFilterError, match="unsupported value type"):
            build_where_clause({"source_filename": ["a.pdf", "b.pdf"]}, config)  # type: ignore[dict-item]

    def test_accepts_bool_value(self, config: RetrievalSearchConfig) -> None:
        config2 = RetrievalSearchConfig(allowed_metadata_filter_fields=["flag"])
        assert build_where_clause({"flag": True}, config2) == {"flag": True}

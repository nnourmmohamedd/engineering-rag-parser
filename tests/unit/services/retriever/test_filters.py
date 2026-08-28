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
            build_where_clause({"source_filename": {"nested": "dict"}}, config)  # type: ignore[dict-item]

    def test_rejects_unsupported_value_type_inside_a_list(self, config: RetrievalSearchConfig) -> None:
        with pytest.raises(InvalidFilterError, match="unsupported value type"):
            build_where_clause({"source_filename": ["a.pdf", None]}, config)  # type: ignore[list-item]

    def test_accepts_bool_value(self, config: RetrievalSearchConfig) -> None:
        config2 = RetrievalSearchConfig(allowed_metadata_filter_fields=["flag"])
        assert build_where_clause({"flag": True}, config2) == {"flag": True}


class TestMembershipSelection:
    """A list/tuple value scopes the query to a set — how selected-document filtering works."""

    def test_list_becomes_native_in_clause(self, config: RetrievalSearchConfig) -> None:
        where = build_where_clause({"source_filename": ["a.pdf", "b.pdf"]}, config)
        assert where == {"source_filename": {"$in": ["a.pdf", "b.pdf"]}}

    def test_tuple_is_accepted_too(self, config: RetrievalSearchConfig) -> None:
        where = build_where_clause({"source_filename": ("a.pdf", "b.pdf")}, config)
        assert where == {"source_filename": {"$in": ["a.pdf", "b.pdf"]}}

    def test_single_element_list_collapses_to_equality(self, config: RetrievalSearchConfig) -> None:
        # Semantically identical to `$in` with one member, but simpler for Chroma to match.
        assert build_where_clause({"source_filename": ["a.pdf"]}, config) == {"source_filename": "a.pdf"}

    def test_duplicates_are_removed_preserving_order(self, config: RetrievalSearchConfig) -> None:
        where = build_where_clause({"source_filename": ["b.pdf", "a.pdf", "b.pdf"]}, config)
        assert where == {"source_filename": {"$in": ["b.pdf", "a.pdf"]}}

    def test_empty_list_is_rejected_rather_than_matching_nothing(self, config: RetrievalSearchConfig) -> None:
        # An empty selection silently matching nothing would be a dangerous default.
        with pytest.raises(InvalidFilterError, match="empty list"):
            build_where_clause({"source_filename": []}, config)

    def test_membership_combines_with_other_fields(self, config: RetrievalSearchConfig) -> None:
        where = build_where_clause({"source_filename": ["a.pdf", "b.pdf"], "content_type": "table"}, config)
        assert where == {
            "$and": [{"content_type": "table"}, {"source_filename": {"$in": ["a.pdf", "b.pdf"]}}]
        }

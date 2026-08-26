"""Adversarial tests for selected-document retrieval isolation.

The chatbot lets a user select a subset of documents and promises that an
answer is grounded *only* in those documents. That promise is worthless if
isolation is implemented by retrieving globally and hiding disallowed rows
afterwards, so these tests attack the boundary directly:

- unselected content must never appear in any hit, in either index;
- the restriction must be expressed as a real query-time clause (Chroma
  ``$in`` / BM25 pre-truncation filter), not a post-hoc slice;
- an empty selection must fail loudly rather than silently matching
  everything (the dangerous default);
- a selection naming an unknown document must not fall back to global scope.

``tests/integration/api`` covers the same guarantees end to end through the
real pipeline; these are the fast, deterministic unit-level proofs.
"""

from __future__ import annotations

import pytest

from engineering_rag.databases.bm25.config import BM25Config
from engineering_rag.databases.bm25.index import build_bm25_index, load_bm25_index
from engineering_rag.databases.bm25.models import BM25CorpusRecord
from engineering_rag.services.retriever.bm25_retriever import BM25Retriever
from engineering_rag.services.retriever.config import RetrievalSearchConfig
from engineering_rag.services.retriever.errors import InvalidFilterError
from engineering_rag.services.retriever.filters import build_where_clause

#: Three documents that all match the same query text, so any leak is visible:
#: a correct implementation returns only the selected document's chunks even
#: though every chunk is a strong lexical/semantic match for the query.
_SECRET = "classified merger valuation figure"

RECORDS = [
    BM25CorpusRecord(
        chunk_id="doc_a_c1",
        retrieval_text="control valve calibration procedure",
        content_hash="ha1",
        source_filename="a.pdf",
        document_id="doc_a",
        metadata={"document_id": "doc_a", "source_filename": "a.pdf"},
    ),
    BM25CorpusRecord(
        chunk_id="doc_b_c1",
        retrieval_text="control valve calibration procedure",
        content_hash="hb1",
        source_filename="b.pdf",
        document_id="doc_b",
        metadata={"document_id": "doc_b", "source_filename": "b.pdf"},
    ),
    BM25CorpusRecord(
        chunk_id="doc_secret_c1",
        retrieval_text=f"control valve calibration procedure {_SECRET}",
        content_hash="hs1",
        source_filename="secret.pdf",
        document_id="doc_secret",
        metadata={"document_id": "doc_secret", "source_filename": "secret.pdf"},
    ),
]


@pytest.fixture
def retriever(tmp_path) -> BM25Retriever:
    config = BM25Config(index_path=str(tmp_path / "idx"))
    build_bm25_index(list(RECORDS), config, collection_name="isolation", chroma_persistence_path="x")
    return BM25Retriever(index=load_bm25_index(config), config=RetrievalSearchConfig())


@pytest.fixture
def search_config() -> RetrievalSearchConfig:
    return RetrievalSearchConfig()


class TestChromaClauseIsRestrictedAtQueryTime:
    """The Chroma side must emit a real ``where`` clause, not rely on post-filtering."""

    def test_single_selected_document_emits_equality_clause(
        self, search_config: RetrievalSearchConfig
    ) -> None:
        assert build_where_clause({"document_id": ["doc_a"]}, search_config) == {"document_id": "doc_a"}

    def test_multi_document_selection_emits_in_clause(self, search_config: RetrievalSearchConfig) -> None:
        where = build_where_clause({"document_id": ["doc_a", "doc_b"]}, search_config)
        assert where == {"document_id": {"$in": ["doc_a", "doc_b"]}}
        # The unselected document must not appear anywhere in the clause.
        assert "doc_secret" not in repr(where)

    def test_empty_selection_is_refused_not_silently_global(
        self, search_config: RetrievalSearchConfig
    ) -> None:
        with pytest.raises(InvalidFilterError, match="empty list"):
            build_where_clause({"document_id": []}, search_config)

    def test_no_filter_at_all_is_distinguishable_from_empty_selection(
        self, search_config: RetrievalSearchConfig
    ) -> None:
        # `None` (unscoped) and "empty selection" must never be conflated: the
        # former is a deliberate global query, the latter is a caller bug.
        assert build_where_clause({}, search_config) is None


class TestBM25SelectionIsolation:
    def test_single_document_selection_excludes_all_others(self, retriever: BM25Retriever) -> None:
        outcome = retriever.search(
            "control valve calibration", top_k=10, metadata_filters={"document_id": ["doc_a"]}
        )
        assert {h.chunk_id for h in outcome.hits} == {"doc_a_c1"}

    def test_multi_document_selection_returns_exactly_the_selection(self, retriever: BM25Retriever) -> None:
        outcome = retriever.search(
            "control valve calibration", top_k=10, metadata_filters={"document_id": ["doc_a", "doc_b"]}
        )
        assert {h.chunk_id for h in outcome.hits} == {"doc_a_c1", "doc_b_c1"}

    def test_unselected_document_text_never_leaks_into_hits(self, retriever: BM25Retriever) -> None:
        """The strongest match for this query lives in the *unselected* document."""
        outcome = retriever.search(_SECRET, top_k=10, metadata_filters={"document_id": ["doc_a", "doc_b"]})
        assert all(h.document_id in {"doc_a", "doc_b"} for h in outcome.hits)
        for hit in outcome.hits:
            assert _SECRET not in hit.retrieval_text
            assert hit.source_filename != "secret.pdf"

    def test_unknown_document_id_yields_nothing_not_everything(self, retriever: BM25Retriever) -> None:
        """A stale/deleted document ID must not silently fall back to global scope."""
        outcome = retriever.search(
            "control valve calibration", top_k=10, metadata_filters={"document_id": ["doc_does_not_exist"]}
        )
        assert outcome.hits == []

    def test_mixed_valid_and_unknown_ids_returns_only_the_valid_subset(
        self, retriever: BM25Retriever
    ) -> None:
        outcome = retriever.search(
            "control valve calibration",
            top_k=10,
            metadata_filters={"document_id": ["doc_a", "doc_does_not_exist"]},
        )
        assert {h.chunk_id for h in outcome.hits} == {"doc_a_c1"}

    def test_filtering_happens_before_truncation_so_top_k_is_honest(self, retriever: BM25Retriever) -> None:
        """With top_k=1 and a selection, the single hit must come from the selection.

        If filtering were applied *after* truncating to top_k, an unselected
        document ranking first would consume the only slot and this would
        return zero hits.
        """
        outcome = retriever.search(_SECRET, top_k=1, metadata_filters={"document_id": ["doc_a"]})
        assert len(outcome.hits) == 1
        assert outcome.hits[0].document_id == "doc_a"

    def test_ranks_are_renumbered_within_the_selection(self, retriever: BM25Retriever) -> None:
        outcome = retriever.search(
            "control valve calibration", top_k=10, metadata_filters={"document_id": ["doc_b"]}
        )
        assert [h.rank for h in outcome.hits] == [1]

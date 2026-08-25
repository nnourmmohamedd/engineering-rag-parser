from __future__ import annotations

import pytest

from engineering_rag.databases.bm25.config import BM25Config
from engineering_rag.databases.bm25.index import build_bm25_index, load_bm25_index
from engineering_rag.databases.bm25.models import BM25CorpusRecord
from engineering_rag.services.retriever.bm25_retriever import BM25Retriever
from engineering_rag.services.retriever.config import RetrievalSearchConfig
from engineering_rag.services.retriever.errors import InvalidFilterError

RECORDS = [
    BM25CorpusRecord(
        chunk_id="c1",
        retrieval_text="control valve PT-101 flow",
        content_hash="h1",
        source_filename="a.pdf",
        metadata={"source_filename": "a.pdf"},
    ),
    BM25CorpusRecord(
        chunk_id="c2",
        retrieval_text="control valve FT_203 flow",
        content_hash="h2",
        source_filename="b.pdf",
        metadata={"source_filename": "b.pdf"},
    ),
]


@pytest.fixture
def retriever(tmp_path):
    config = BM25Config(index_path=str(tmp_path / "idx"))
    build_bm25_index(list(RECORDS), config, collection_name="test", chroma_persistence_path="x")
    handle = load_bm25_index(config)
    return BM25Retriever(index=handle, config=RetrievalSearchConfig())


class TestBM25RetrieverFiltering:
    def test_no_filter_returns_all_matches(self, retriever: BM25Retriever) -> None:
        outcome = retriever.search("control valve", top_k=10)
        assert {h.chunk_id for h in outcome.hits} == {"c1", "c2"}

    def test_filter_narrows_to_matching_source(self, retriever: BM25Retriever) -> None:
        outcome = retriever.search("control valve", top_k=10, metadata_filters={"source_filename": "a.pdf"})
        assert {h.chunk_id for h in outcome.hits} == {"c1"}

    def test_unsupported_filter_field_rejected(self, retriever: BM25Retriever) -> None:
        with pytest.raises(InvalidFilterError):
            retriever.search("control valve", top_k=10, metadata_filters={"not_allowed": "x"})

    def test_empty_query_returns_no_hits(self, retriever: BM25Retriever) -> None:
        outcome = retriever.search("", top_k=10)
        assert outcome.hits == []

    def test_ranks_are_renumbered_after_filtering(self, retriever: BM25Retriever) -> None:
        outcome = retriever.search("control valve", top_k=10, metadata_filters={"source_filename": "b.pdf"})
        assert outcome.hits[0].rank == 1
        assert outcome.hits[0].bm25_rank is not None

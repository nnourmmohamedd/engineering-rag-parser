from __future__ import annotations

from pathlib import Path

import pytest

from engineering_rag.databases.bm25.config import BM25Config
from engineering_rag.databases.bm25.errors import BM25IndexNotFoundError, CorpusValidationError
from engineering_rag.databases.bm25.index import build_bm25_index, load_bm25_index
from engineering_rag.databases.bm25.models import BM25CorpusRecord

RECORDS = [
    BM25CorpusRecord(
        chunk_id="c1",
        retrieval_text="The control valve PT-101 regulates flow per IEC 61511.",
        content_hash="h1",
        document_id="doc1",
        source_filename="a.pdf",
    ),
    BM25CorpusRecord(
        chunk_id="c2",
        retrieval_text="Front-End Engineering Design FEED phase activities.",
        content_hash="h2",
        document_id="doc1",
        source_filename="a.pdf",
    ),
    BM25CorpusRecord(
        chunk_id="c3",
        retrieval_text="Instrument index lists tag numbers like FT_203 and PT-101.",
        content_hash="h3",
        document_id="doc1",
        source_filename="a.pdf",
    ),
]


@pytest.fixture
def config(tmp_path):
    return BM25Config(index_path=str(tmp_path / "idx"))


class TestBuildAndSearch:
    def test_build_reports_correct_corpus_count(self, config) -> None:
        manifest = build_bm25_index(
            list(RECORDS), config, collection_name="test", chroma_persistence_path="x"
        )
        assert manifest.corpus_count == 3
        assert sorted(manifest.chunk_ids) == ["c1", "c2", "c3"]

    def test_exact_lexical_ranking_on_fixed_corpus(self, config) -> None:
        build_bm25_index(list(RECORDS), config, collection_name="test", chroma_persistence_path="x")
        handle = load_bm25_index(config)
        hits = handle.search("PT-101", top_k=3)
        assert [h.record.chunk_id for h in hits[:2]] == ["c1", "c3"]
        assert hits[0].bm25_score > hits[1].bm25_score > 0

    def test_save_load_equivalence(self, config) -> None:
        build_bm25_index(list(RECORDS), config, collection_name="test", chroma_persistence_path="x")
        handle_a = load_bm25_index(config)
        handle_b = load_bm25_index(config)
        hits_a = handle_a.search("FEED phase", top_k=3)
        hits_b = handle_b.search("FEED phase", top_k=3)
        assert [h.record.chunk_id for h in hits_a] == [h.record.chunk_id for h in hits_b]
        assert [h.bm25_score for h in hits_a] == [h.bm25_score for h in hits_b]

    def test_empty_query_returns_no_hits(self, config) -> None:
        build_bm25_index(list(RECORDS), config, collection_name="test", chroma_persistence_path="x")
        handle = load_bm25_index(config)
        assert handle.search("   ", top_k=5) == []

    def test_missing_index_raises(self, config) -> None:
        with pytest.raises(BM25IndexNotFoundError):
            load_bm25_index(config)

    def test_corrupted_index_raises(self, config) -> None:
        build_bm25_index(list(RECORDS), config, collection_name="test", chroma_persistence_path="x")
        Path(config.index_path, "data.csc.index.npy").unlink()
        with pytest.raises(Exception):  # noqa: B017, PT011 - bm25s/numpy raise their own load error
            load_bm25_index(config)


class TestCorpusValidation:
    def test_duplicate_chunk_ids_rejected(self, config) -> None:
        records = list(RECORDS) + [RECORDS[0]]
        with pytest.raises(CorpusValidationError, match="duplicate"):
            build_bm25_index(records, config, collection_name="test", chroma_persistence_path="x")

    def test_missing_text_rejected(self, config) -> None:
        records = [
            BM25CorpusRecord(chunk_id="c1", retrieval_text="", content_hash="h1"),
        ]
        with pytest.raises(CorpusValidationError, match="retrieval_text"):
            build_bm25_index(records, config, collection_name="test", chroma_persistence_path="x")

    def test_whitespace_only_text_rejected(self, config) -> None:
        records = [
            BM25CorpusRecord(chunk_id="c1", retrieval_text="   ", content_hash="h1"),
        ]
        with pytest.raises(CorpusValidationError):
            build_bm25_index(records, config, collection_name="test", chroma_persistence_path="x")


class TestIdempotentRebuild:
    def test_rebuild_without_force_is_noop(self, config) -> None:
        manifest_1 = build_bm25_index(
            list(RECORDS), config, collection_name="test", chroma_persistence_path="x"
        )
        manifest_2 = build_bm25_index(
            list(RECORDS), config, collection_name="test", chroma_persistence_path="x"
        )
        assert manifest_1.generated_at_utc == manifest_2.generated_at_utc
        assert manifest_1.corpus_fingerprint == manifest_2.corpus_fingerprint

    def test_force_rebuilds(self, config) -> None:
        manifest_1 = build_bm25_index(
            list(RECORDS), config, collection_name="test", chroma_persistence_path="x"
        )
        manifest_2 = build_bm25_index(
            list(RECORDS), config, collection_name="test", chroma_persistence_path="x", force=True
        )
        assert manifest_1.corpus_fingerprint == manifest_2.corpus_fingerprint
        assert manifest_1.generated_at_utc <= manifest_2.generated_at_utc

    def test_fingerprint_stable_under_input_reordering(self, config) -> None:
        manifest_1 = build_bm25_index(
            list(RECORDS), config, collection_name="test", chroma_persistence_path="x"
        )
        reordered = list(reversed(RECORDS))
        manifest_2 = build_bm25_index(
            reordered, config, collection_name="test", chroma_persistence_path="x", force=True
        )
        assert manifest_1.corpus_fingerprint == manifest_2.corpus_fingerprint

    def test_fingerprint_changes_when_corpus_changes(self, config) -> None:
        manifest_1 = build_bm25_index(
            list(RECORDS), config, collection_name="test", chroma_persistence_path="x"
        )
        changed = list(RECORDS) + [
            BM25CorpusRecord(chunk_id="c4", retrieval_text="new chunk text", content_hash="h4")
        ]
        manifest_2 = build_bm25_index(
            changed, config, collection_name="test", chroma_persistence_path="x", force=True
        )
        assert manifest_1.corpus_fingerprint != manifest_2.corpus_fingerprint

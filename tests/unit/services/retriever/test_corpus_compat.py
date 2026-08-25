from __future__ import annotations

from datetime import datetime, timezone

import pytest

from engineering_rag.databases.bm25.models import BM25Manifest
from engineering_rag.services.retriever.corpus_compat import (
    CorpusCompatibilityError,
    check_corpus_compatibility,
    require_compatible,
)


def _manifest(**overrides: object) -> BM25Manifest:
    base: dict[str, object] = {
        "generated_at_utc": datetime.now(timezone.utc),
        "collection_name": "engineering_documents_v1",
        "chroma_persistence_path": "data/output/databases/chroma",
        "corpus_count": 2,
        "corpus_fingerprint": "abc123",
        "chunk_ids": ["c1", "c2"],
        "document_ids": ["doc1"],
        "source_filenames": ["a.pdf"],
        "content_hashes": {"c1": "h1", "c2": "h2"},
        "chunk_schema_versions": ["1.0.0"],
        "bm25_library": "bm25s",
        "bm25_library_version": "0.3.11",
        "tokenizer_version": "1.0.0",
        "method": "lucene",
        "k1": 1.2,
        "b": 0.75,
    }
    base.update(overrides)
    return BM25Manifest.model_validate(base)


class TestCorpusCompatibility:
    def test_exact_match_passes(self) -> None:
        report = check_corpus_compatibility(
            collection_name="engineering_documents_v1",
            chroma_ids=["c1", "c2"],
            chroma_document_ids=["doc1"],
            chroma_source_filenames=["a.pdf"],
            chroma_content_hashes={"c1": "h1", "c2": "h2"},
            chroma_schema_versions=["1.0.0"],
            bm25_manifest=_manifest(),
        )
        assert report.compatible
        require_compatible(report)  # must not raise

    def test_count_mismatch_fails(self) -> None:
        report = check_corpus_compatibility(
            collection_name="engineering_documents_v1",
            chroma_ids=["c1", "c2", "c3"],
            chroma_document_ids=["doc1"],
            chroma_source_filenames=["a.pdf"],
            chroma_content_hashes={"c1": "h1", "c2": "h2", "c3": "h3"},
            chroma_schema_versions=["1.0.0"],
            bm25_manifest=_manifest(),
        )
        assert not report.compatible
        assert not report.record_count_match
        with pytest.raises(CorpusCompatibilityError):
            require_compatible(report)

    def test_missing_chunk_fails(self) -> None:
        report = check_corpus_compatibility(
            collection_name="engineering_documents_v1",
            chroma_ids=["c1", "c3"],
            chroma_document_ids=["doc1"],
            chroma_source_filenames=["a.pdf"],
            chroma_content_hashes={"c1": "h1", "c3": "h3"},
            chroma_schema_versions=["1.0.0"],
            bm25_manifest=_manifest(),
        )
        assert not report.compatible
        assert "c3" in report.missing_from_bm25
        assert "c2" in report.missing_from_chroma

    def test_content_hash_mismatch_fails(self) -> None:
        report = check_corpus_compatibility(
            collection_name="engineering_documents_v1",
            chroma_ids=["c1", "c2"],
            chroma_document_ids=["doc1"],
            chroma_source_filenames=["a.pdf"],
            chroma_content_hashes={"c1": "DIFFERENT", "c2": "h2"},
            chroma_schema_versions=["1.0.0"],
            bm25_manifest=_manifest(),
        )
        assert not report.compatible
        assert report.content_hash_mismatches == ["c1"]

    def test_source_hash_mismatch_via_filename_set_fails(self) -> None:
        report = check_corpus_compatibility(
            collection_name="engineering_documents_v1",
            chroma_ids=["c1", "c2"],
            chroma_document_ids=["doc1"],
            chroma_source_filenames=["different.pdf"],
            chroma_content_hashes={"c1": "h1", "c2": "h2"},
            chroma_schema_versions=["1.0.0"],
            bm25_manifest=_manifest(),
        )
        assert not report.compatible
        assert not report.source_filename_set_match

    def test_schema_version_mismatch_fails(self) -> None:
        report = check_corpus_compatibility(
            collection_name="engineering_documents_v1",
            chroma_ids=["c1", "c2"],
            chroma_document_ids=["doc1"],
            chroma_source_filenames=["a.pdf"],
            chroma_content_hashes={"c1": "h1", "c2": "h2"},
            chroma_schema_versions=["2.0.0"],
            bm25_manifest=_manifest(),
        )
        assert not report.compatible
        assert not report.schema_version_match

    def test_collection_name_mismatch_fails(self) -> None:
        report = check_corpus_compatibility(
            collection_name="other_collection",
            chroma_ids=["c1", "c2"],
            chroma_document_ids=["doc1"],
            chroma_source_filenames=["a.pdf"],
            chroma_content_hashes={"c1": "h1", "c2": "h2"},
            chroma_schema_versions=["1.0.0"],
            bm25_manifest=_manifest(),
        )
        assert not report.compatible
        assert not report.collection_name_match

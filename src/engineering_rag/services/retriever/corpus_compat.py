"""Strict compatibility gate between the live Chroma collection and a persistent BM25 index.

Hybrid search must never fuse rankings computed over two different versions
of the corpus (e.g. a Chroma collection reindexed after the BM25 index was
last built). This module is the single place that decides "compatible" vs.
"refuse to run" — ``pipelines/retrieval_pipeline.py`` calls it before every
hybrid or hybrid-rerank search and raises on any mismatch.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from engineering_rag.databases.bm25.models import BM25Manifest

from .errors import RetrievalError

__all__ = ["CorpusCompatibilityError", "CorpusCompatibilityReport", "check_corpus_compatibility"]


class CorpusCompatibilityError(RetrievalError):
    """Raised when the Chroma collection and the BM25 index describe different corpora."""


class CorpusCompatibilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    compatible: bool
    collection_name_match: bool
    record_count_match: bool
    chunk_id_set_match: bool
    document_id_set_match: bool
    content_hash_match: bool
    source_filename_set_match: bool
    schema_version_match: bool
    missing_from_bm25: list[str] = Field(default_factory=list)
    missing_from_chroma: list[str] = Field(default_factory=list)
    content_hash_mismatches: list[str] = Field(default_factory=list)
    details: list[str] = Field(default_factory=list)


def check_corpus_compatibility(
    *,
    collection_name: str,
    chroma_ids: list[str],
    chroma_document_ids: list[str],
    chroma_source_filenames: list[str],
    chroma_content_hashes: dict[str, str],
    chroma_schema_versions: list[str],
    bm25_manifest: BM25Manifest,
) -> CorpusCompatibilityReport:
    """Compare a live Chroma read against a persisted BM25 manifest. Never mutates either side."""
    details: list[str] = []

    name_match = collection_name == bm25_manifest.collection_name
    if not name_match:
        details.append(
            f"collection_name mismatch: chroma={collection_name!r} bm25={bm25_manifest.collection_name!r}"
        )

    chroma_id_set = set(chroma_ids)
    bm25_id_set = set(bm25_manifest.chunk_ids)
    count_match = len(chroma_ids) == bm25_manifest.corpus_count
    id_set_match = chroma_id_set == bm25_id_set
    missing_from_bm25 = sorted(chroma_id_set - bm25_id_set)
    missing_from_chroma = sorted(bm25_id_set - chroma_id_set)
    if not count_match:
        details.append(f"record count mismatch: chroma={len(chroma_ids)} bm25={bm25_manifest.corpus_count}")
    if missing_from_bm25:
        details.append(f"{len(missing_from_bm25)} chunk_id(s) in Chroma but not in the BM25 index")
    if missing_from_chroma:
        details.append(f"{len(missing_from_chroma)} chunk_id(s) in the BM25 index but not in Chroma")

    doc_id_match = set(chroma_document_ids) == set(bm25_manifest.document_ids)
    if not doc_id_match:
        details.append("document_id set differs between Chroma and the BM25 index")

    filename_match = set(chroma_source_filenames) == set(bm25_manifest.source_filenames)
    if not filename_match:
        details.append("source_filename set differs between Chroma and the BM25 index")

    schema_match = (
        set(chroma_schema_versions) <= set(bm25_manifest.chunk_schema_versions) or not chroma_schema_versions
    )
    if chroma_schema_versions and not schema_match:
        details.append(
            f"chunk_schema_version mismatch: chroma={sorted(set(chroma_schema_versions))} "
            f"bm25={sorted(set(bm25_manifest.chunk_schema_versions))}"
        )

    hash_mismatches = sorted(
        cid
        for cid in chroma_id_set & bm25_id_set
        if chroma_content_hashes.get(cid)
        and bm25_manifest.content_hashes.get(cid)
        and chroma_content_hashes[cid] != bm25_manifest.content_hashes[cid]
    )
    hash_match = not hash_mismatches
    if hash_mismatches:
        details.append(
            f"{len(hash_mismatches)} chunk_id(s) with mismatched content_hash: {hash_mismatches[:5]}"
        )

    compatible = (
        name_match
        and count_match
        and id_set_match
        and doc_id_match
        and filename_match
        and hash_match
        and schema_match
    )

    return CorpusCompatibilityReport(
        compatible=compatible,
        collection_name_match=name_match,
        record_count_match=count_match,
        chunk_id_set_match=id_set_match,
        document_id_set_match=doc_id_match,
        content_hash_match=hash_match,
        source_filename_set_match=filename_match,
        schema_version_match=schema_match,
        missing_from_bm25=missing_from_bm25,
        missing_from_chroma=missing_from_chroma,
        content_hash_mismatches=hash_mismatches,
        details=details,
    )


def require_compatible(report: CorpusCompatibilityReport) -> None:
    """Raise :class:`CorpusCompatibilityError` if ``report`` is not fully compatible."""
    if not report.compatible:
        raise CorpusCompatibilityError(
            "Chroma collection and BM25 index describe different corpora; refusing to run hybrid "
            f"search: {'; '.join(report.details)}. Rebuild the BM25 index with "
            "`engrag-retrieve build-bm25 --profile <profile>`."
        )

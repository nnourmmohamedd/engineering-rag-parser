"""Indexing pipeline unit tests, using a deterministic fake embedder and a
hand-built chunker run fixture — no real BGE model download.

The admission check re-measures every retrieval_text with the *configured*
embedding model's own tokenizer (never the injected embedder's identity), so
these tests configure ``embedding.model_name`` as the small, already-cached
``sentence-transformers/all-MiniLM-L6-v2`` tokenizer (used elsewhere in this
repo's own chunker tests) while still injecting :class:`FakeEmbeddingService`
for the actual vectors — this keeps the whole suite network-free without
weakening what's being tested (tokenizer-match / no-truncation admission
logic is identical regardless of which real tokenizer is configured).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from engineering_rag.databases.chroma.errors import CollectionMismatchError
from engineering_rag.pipelines.indexing_config import IndexingConfig
from engineering_rag.pipelines.indexing_pipeline import IndexingInputError, run_indexing_pipeline
from tests.support.fake_embedder import FakeEmbeddingService

pytestmark = pytest.mark.integration  # touches a real (ephemeral) chromadb + a real cached tokenizer

_TOKENIZER = "sentence-transformers/all-MiniLM-L6-v2"


def _chunk_record(
    chunk_id: str,
    index: int,
    text: str | None = None,
    source_filename: str = "doc.pdf",
    provenance: list[dict[str, Any]] | None = None,
    was_recursively_split: bool = False,
    merged_from_chunk_ids: list[str] | None = None,
) -> dict[str, Any]:
    if text is None:
        text = f"Some faithful chunk content about valve number {index}, unique per chunk."
    return {
        "schema_version": "1.0.0",
        "chunk_id": chunk_id,
        "document_id": "docsha256",
        "source_filename": source_filename,
        "source_sha256": "docsha256",
        "chunk_index": index,
        "content_type": "text",
        "text": text,
        "retrieval_text": text,
        "token_count": 8,
        "tokenizer_name": _TOKENIZER,
        "heading_path": ["Section 1"],
        "section_title": "Section 1",
        "captions": [],
        "labels": ["text"],
        "page_numbers": [1],
        "provenance": provenance if provenance is not None else [],
        "source_element_refs": [f"#/texts/{index}"],
        "parent_chunk_id": None,
        "previous_chunk_id": None,
        "next_chunk_id": None,
        "merged_from_chunk_ids": merged_from_chunk_ids,
        "split_method": "hierarchical",
        "was_recursively_split": was_recursively_split,
        "overlap_tokens_before": 0,
        "table_metadata": None,
        "figure_asset_path": None,
        "figure_page_no": None,
        "is_atomic_overflow": False,
        "parser_warnings": [],
        "warnings": [],
    }


def _write_chunk_run(
    tmp_path: Path,
    *,
    tokenizer_name: str = _TOKENIZER,
    chunker_status: str = "PASS",
    n: int = 5,
    run_id: str = "20260101T000000Z-deadbeef",
    subdir: str = "chunker_run",
    source_filename: str = "doc.pdf",
) -> Path:
    run_dir = tmp_path / subdir
    run_dir.mkdir(parents=True, exist_ok=True)
    records = [_chunk_record(f"chunk_{i:04d}", i, source_filename=source_filename) for i in range(n)]
    (run_dir / "chunks.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    manifest = {
        "run_id": run_id,
        "tokenizer": {"name": tokenizer_name, "max_tokens": 256},
        "source": {"filename": "doc.pdf", "sha256": "docsha256"},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    validation_report = {"status": chunker_status}
    (run_dir / "validation_report.json").write_text(json.dumps(validation_report), encoding="utf-8")
    return run_dir


def _config(tmp_path: Path, collection: str = "test_index") -> IndexingConfig:
    return IndexingConfig.model_validate(
        {
            "embedding": {
                "model_name": _TOKENIZER,
                "expected_dimension": 768,
                "maximum_sequence_length": 256,
            },
            "chroma": {
                "persistence_path": str(tmp_path / "chroma"),
                "collection_name": collection,
            },
            "output_root": str(tmp_path / "reports"),
        }
    )


class TestHappyPath:
    def test_full_run_passes(self, tmp_path: Path) -> None:
        run_dir = _write_chunk_run(tmp_path)
        config = _config(tmp_path)
        result = run_indexing_pipeline(run_dir, config, embedder=FakeEmbeddingService())
        assert result.status in ("PASS", "PASS_WITH_WARNINGS")
        assert result.chunk_count == 5
        assert result.exit_code == 0
        assert (result.run_dir / "index_manifest.json").is_file()
        assert (result.run_dir / "ingestion_report.json").is_file()
        assert (result.run_dir / "index_validation_report.json").is_file()
        assert (result.run_dir / "index_summary.md").is_file()

    def test_accepts_chunks_jsonl_file_directly(self, tmp_path: Path) -> None:
        run_dir = _write_chunk_run(tmp_path)
        config = _config(tmp_path)
        result = run_indexing_pipeline(run_dir / "chunks.jsonl", config, embedder=FakeEmbeddingService())
        assert result.status in ("PASS", "PASS_WITH_WARNINGS")

    def test_manifest_records_config_hash_and_model(self, tmp_path: Path) -> None:
        run_dir = _write_chunk_run(tmp_path)
        config = _config(tmp_path)
        result = run_indexing_pipeline(run_dir, config, embedder=FakeEmbeddingService())
        assert result.manifest.config_hash == config.config_hash()
        assert result.manifest.embedding_dimension == 768


def _stored_metadata(config: IndexingConfig, chunk_id: str) -> dict[str, Any]:
    from engineering_rag.databases.chroma import get_client

    client = get_client(config.chroma.persistence_path, telemetry=config.chroma.telemetry)
    collection = client.get_collection(config.chroma.collection_name)
    got = collection.get(ids=[chunk_id], include=["metadatas"])
    metadatas = got.get("metadatas") or []
    return metadatas[0] if metadatas else {}


class TestProvenance:
    """Bbox provenance must survive indexing (it used to be silently dropped -- see
    docs/chatbot/COMPLETION_REPORT.md) and bbox_reliable must be computed correctly."""

    def test_provenance_and_reliable_bbox_are_persisted(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "chunker_run"
        run_dir.mkdir()
        record = _chunk_record(
            "chunk_0000", 0, provenance=[{"page_no": 3, "bbox": [10.0, 700.0, 200.0, 650.0]}]
        )
        (run_dir / "chunks.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        manifest = {
            "run_id": "run1",
            "tokenizer": {"name": _TOKENIZER, "max_tokens": 256},
            "source": {"filename": "doc.pdf", "sha256": "docsha256"},
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (run_dir / "validation_report.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

        config = _config(tmp_path)
        run_indexing_pipeline(run_dir, config, embedder=FakeEmbeddingService())

        meta = _stored_metadata(config, "chunk_0000")
        assert meta["bbox_reliable"] is True
        stored_provenance = json.loads(meta["provenance"])
        assert stored_provenance == [{"page_no": 3, "bbox": [10.0, 700.0, 200.0, 650.0]}]

    def test_recursively_split_chunk_is_not_bbox_reliable(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "chunker_run"
        run_dir.mkdir()
        record = _chunk_record(
            "chunk_0000",
            0,
            provenance=[{"page_no": 3, "bbox": [10.0, 700.0, 200.0, 650.0]}],
            was_recursively_split=True,
        )
        (run_dir / "chunks.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        manifest = {
            "run_id": "run1",
            "tokenizer": {"name": _TOKENIZER, "max_tokens": 256},
            "source": {"filename": "doc.pdf", "sha256": "docsha256"},
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (run_dir / "validation_report.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

        config = _config(tmp_path)
        run_indexing_pipeline(run_dir, config, embedder=FakeEmbeddingService())

        meta = _stored_metadata(config, "chunk_0000")
        # A bbox reflecting the whole pre-split element must never be presented as exact.
        assert meta.get("bbox_reliable", False) is False

    def test_merged_chunk_is_not_bbox_reliable(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "chunker_run"
        run_dir.mkdir()
        record = _chunk_record(
            "chunk_0000",
            0,
            provenance=[{"page_no": 3, "bbox": [10.0, 700.0, 200.0, 650.0]}],
            merged_from_chunk_ids=["chunk_aaaa", "chunk_bbbb"],
        )
        (run_dir / "chunks.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        manifest = {
            "run_id": "run1",
            "tokenizer": {"name": _TOKENIZER, "max_tokens": 256},
            "source": {"filename": "doc.pdf", "sha256": "docsha256"},
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (run_dir / "validation_report.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

        config = _config(tmp_path)
        run_indexing_pipeline(run_dir, config, embedder=FakeEmbeddingService())

        meta = _stored_metadata(config, "chunk_0000")
        assert meta.get("bbox_reliable", False) is False

    def test_missing_bbox_is_not_reliable_but_page_no_survives(self, tmp_path: Path) -> None:
        """A table row with no Docling provenance bbox (see type_handlers/tables.py's
        fallback) must never be claimed reliable, even though the page number is real."""
        run_dir = tmp_path / "chunker_run"
        run_dir.mkdir()
        record = _chunk_record("chunk_0000", 0, provenance=[{"page_no": 7, "bbox": None}])
        (run_dir / "chunks.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        manifest = {
            "run_id": "run1",
            "tokenizer": {"name": _TOKENIZER, "max_tokens": 256},
            "source": {"filename": "doc.pdf", "sha256": "docsha256"},
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (run_dir / "validation_report.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

        config = _config(tmp_path)
        run_indexing_pipeline(run_dir, config, embedder=FakeEmbeddingService())

        meta = _stored_metadata(config, "chunk_0000")
        assert meta.get("bbox_reliable", False) is False
        assert json.loads(meta["provenance"]) == [{"page_no": 7, "bbox": None}]

    def test_no_provenance_omits_the_field_entirely(self, tmp_path: Path) -> None:
        """An empty provenance list is genuinely no information -- chroma_safe_metadata
        omits it rather than storing an empty-list placeholder (matches every other
        list-valued metadata field's convention)."""
        run_dir = _write_chunk_run(tmp_path)  # default fixture: provenance=[]
        config = _config(tmp_path)
        run_indexing_pipeline(run_dir, config, embedder=FakeEmbeddingService())

        meta = _stored_metadata(config, "chunk_0000")
        assert "provenance" not in meta
        assert meta.get("bbox_reliable", False) is False


class TestIdempotency:
    def test_rerun_same_input_produces_no_duplicates(self, tmp_path: Path) -> None:
        run_dir = _write_chunk_run(tmp_path)
        config = _config(tmp_path)
        run_indexing_pipeline(run_dir, config, embedder=FakeEmbeddingService())
        time.sleep(1.1)  # run directories are timestamp-named at 1s resolution; avoid a collision
        result2 = run_indexing_pipeline(run_dir, config, embedder=FakeEmbeddingService())
        assert result2.status in ("PASS", "PASS_WITH_WARNINGS")
        ingestion = json.loads((result2.run_dir / "ingestion_report.json").read_text())
        assert ingestion["final_count"] == 5
        assert ingestion["inserted_ids"] == []
        assert len(ingestion["existing_identical_ids"]) == 5

    def test_rerun_with_different_chunk_run_id_only_is_still_idempotent(self, tmp_path: Path) -> None:
        """Identical text, identical filename, only the chunker's ``run_id`` differs between
        reruns (the normal case: every chunker run gets a fresh timestamp-based run_id even when
        nothing about the source content changed). Regression test for chunk_run_id leaking into
        the content-hash computation."""
        run_dir_a = _write_chunk_run(tmp_path, run_id="20260101T000000Z-deadbeef", subdir="run_a")
        config = _config(tmp_path)
        run_indexing_pipeline(run_dir_a, config, embedder=FakeEmbeddingService())
        time.sleep(1.1)  # run directories are timestamp-named at 1s resolution; avoid a collision

        run_dir_b = _write_chunk_run(tmp_path, run_id="20260102T000000Z-c0ffee00", subdir="run_b")
        result2 = run_indexing_pipeline(run_dir_b, config, embedder=FakeEmbeddingService())

        assert result2.status in ("PASS", "PASS_WITH_WARNINGS")
        ingestion = json.loads((result2.run_dir / "ingestion_report.json").read_text())
        assert ingestion["inserted_ids"] == []
        assert len(ingestion["existing_identical_ids"]) == 5

    def test_rerun_with_different_source_filename_only_is_still_idempotent(self, tmp_path: Path) -> None:
        """Identical text, identical chunk_run_id, only ``source_filename`` differs (the exact
        production scenario: a document already indexed via the CLI under its original filename
        gets re-uploaded through the chatbot, which stages it under a generated storage name).
        Regression test for source_filename leaking into the content-hash computation."""
        run_dir_a = _write_chunk_run(tmp_path, subdir="run_a", source_filename="original.pdf")
        config = _config(tmp_path)
        run_indexing_pipeline(run_dir_a, config, embedder=FakeEmbeddingService())
        time.sleep(1.1)  # run directories are timestamp-named at 1s resolution; avoid a collision

        run_dir_b = _write_chunk_run(tmp_path, subdir="run_b", source_filename="a1b2c3d4e5f6.pdf")
        result2 = run_indexing_pipeline(run_dir_b, config, embedder=FakeEmbeddingService())

        assert result2.status in ("PASS", "PASS_WITH_WARNINGS")
        ingestion = json.loads((result2.run_dir / "ingestion_report.json").read_text())
        assert ingestion["inserted_ids"] == []
        assert len(ingestion["existing_identical_ids"]) == 5

    def test_rerun_with_different_run_id_and_filename_is_still_idempotent(self, tmp_path: Path) -> None:
        """Both chunk_run_id and source_filename differ at once -- the real production failure
        this bug was diagnosed from (a chatbot re-upload of a document already indexed via the
        CLI under a different original filename)."""
        run_dir_a = _write_chunk_run(
            tmp_path, run_id="20260101T000000Z-deadbeef", subdir="run_a", source_filename="original.pdf"
        )
        config = _config(tmp_path)
        run_indexing_pipeline(run_dir_a, config, embedder=FakeEmbeddingService())
        time.sleep(1.1)  # run directories are timestamp-named at 1s resolution; avoid a collision

        run_dir_b = _write_chunk_run(
            tmp_path,
            run_id="20260102T000000Z-c0ffee00",
            subdir="run_b",
            source_filename="a1b2c3d4e5f6.pdf",
        )
        result2 = run_indexing_pipeline(run_dir_b, config, embedder=FakeEmbeddingService())

        assert result2.status in ("PASS", "PASS_WITH_WARNINGS")
        ingestion = json.loads((result2.run_dir / "ingestion_report.json").read_text())
        assert ingestion["inserted_ids"] == []
        assert len(ingestion["existing_identical_ids"]) == 5

    def test_model_mismatch_on_rerun_raises(self, tmp_path: Path) -> None:
        run_dir = _write_chunk_run(tmp_path)
        config = _config(tmp_path)
        run_indexing_pipeline(run_dir, config, embedder=FakeEmbeddingService())
        time.sleep(1.1)
        with pytest.raises(CollectionMismatchError):
            run_indexing_pipeline(
                run_dir, config, embedder=FakeEmbeddingService(model_name="a-different-model")
            )


class TestAdmissionRejections:
    def test_tokenizer_mismatch_rejected(self, tmp_path: Path) -> None:
        run_dir = _write_chunk_run(tmp_path, tokenizer_name="some/other-tokenizer")
        config = _config(tmp_path)
        with pytest.raises(IndexingInputError, match="tokenizer mismatch"):
            run_indexing_pipeline(run_dir, config, embedder=FakeEmbeddingService())

    def test_failed_chunker_validation_rejected(self, tmp_path: Path) -> None:
        run_dir = _write_chunk_run(tmp_path, chunker_status="FAIL")
        config = _config(tmp_path)
        with pytest.raises(IndexingInputError, match="did not pass validation"):
            run_indexing_pipeline(run_dir, config, embedder=FakeEmbeddingService())

    def test_missing_manifest_rejected(self, tmp_path: Path) -> None:
        run_dir = _write_chunk_run(tmp_path)
        (run_dir / "manifest.json").unlink()
        config = _config(tmp_path)
        with pytest.raises(IndexingInputError, match="manifest.json"):
            run_indexing_pipeline(run_dir, config, embedder=FakeEmbeddingService())

    def test_missing_input_rejected(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        with pytest.raises(IndexingInputError):
            run_indexing_pipeline(tmp_path / "does-not-exist", config, embedder=FakeEmbeddingService())

    def test_oversized_chunk_rejected(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "chunker_run"
        run_dir.mkdir()
        huge_text = "word " * 2000  # far more than 256 tokens under MiniLM's tokenizer
        record = _chunk_record("chunk_0000", 0, text=huge_text)
        (run_dir / "chunks.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        manifest = {
            "run_id": "run1",
            "tokenizer": {"name": _TOKENIZER, "max_tokens": 256},
            "source": {"filename": "doc.pdf", "sha256": "docsha256"},
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (run_dir / "validation_report.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

        config = _config(tmp_path)
        with pytest.raises(IndexingInputError, match="exceed"):
            run_indexing_pipeline(run_dir, config, embedder=FakeEmbeddingService())

    def test_unsupported_chunk_schema_rejected(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "chunker_run"
        run_dir.mkdir()
        r1 = _chunk_record("chunk_0000", 0)
        r2 = _chunk_record("chunk_0001", 1)
        r2["schema_version"] = "9.9.9"  # inconsistent with r1 -> unsupported/ambiguous schema
        (run_dir / "chunks.jsonl").write_text(
            "\n".join(json.dumps(r) for r in (r1, r2)) + "\n", encoding="utf-8"
        )
        manifest = {
            "run_id": "run1",
            "tokenizer": {"name": _TOKENIZER, "max_tokens": 256},
            "source": {"filename": "doc.pdf", "sha256": "docsha256"},
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (run_dir / "validation_report.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

        config = _config(tmp_path)
        with pytest.raises(IndexingInputError, match="schema_version"):
            run_indexing_pipeline(run_dir, config, embedder=FakeEmbeddingService())


class TestPortableManifestPaths:
    def test_input_inside_repo_records_relative_path(self, tmp_path: Path) -> None:
        """A chunk run under the repo's own data/output/chunker/ is recorded as a
        relative, portable path in the manifest (not a machine-specific absolute path)."""
        from engineering_rag.utils.paths import repo_root

        run_dir = repo_root() / "data" / "output" / "chunker" / "_cli_test_fixture_tmp"
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            records = [_chunk_record(f"chunk_{i:04d}", i) for i in range(2)]
            (run_dir / "chunks.jsonl").write_text(
                "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
            )
            manifest = {
                "run_id": "run1",
                "tokenizer": {"name": _TOKENIZER, "max_tokens": 256},
                "source": {"filename": "doc.pdf", "sha256": "docsha256"},
            }
            (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (run_dir / "validation_report.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

            config = _config(tmp_path)
            result = run_indexing_pipeline(run_dir, config, embedder=FakeEmbeddingService())
            assert not Path(result.manifest.input_chunks_jsonl_path).is_absolute()
            assert result.status == "PASS"
        finally:
            import shutil

            shutil.rmtree(run_dir, ignore_errors=True)

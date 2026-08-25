"""Retrieval pipeline orchestration tests: open/inspect/validate/search/evaluate.

Builds a small, real, ephemeral Chroma collection via the existing
``databases.chroma`` adapter (exactly as the indexing pipeline would), then
exercises ``pipelines/retrieval_pipeline.py`` against it with the
deterministic :class:`FakeEmbeddingService` — no real model, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_rag.databases.chroma import (
    CollectionIdentity,
    chroma_safe_metadata,
    content_hash,
    get_client,
    ingest_batch,
    open_or_create_collection,
)
from engineering_rag.databases.chroma.config import ChromaConfig
from engineering_rag.pipelines.retrieval_config import RetrievalConfig
from engineering_rag.pipelines.retrieval_pipeline import (
    inspect_collection,
    run_evaluation_pipeline,
    run_search,
    validate_environment,
)
from engineering_rag.services.retriever.errors import CollectionNotFoundError
from tests.support.fake_embedder import FakeEmbeddingService

_MODEL_NAME = "fake-embedder-for-tests"


def _build_indexed_collection(tmp_path: Path, *, collection_name: str = "test_collection") -> ChromaConfig:
    chroma_config = ChromaConfig(persistence_path=tmp_path / "chroma", collection_name=collection_name)
    identity = CollectionIdentity(
        model_name=_MODEL_NAME,
        embedding_dimension=768,
        distance_metric="cosine",
        tokenizer_name=_MODEL_NAME,
    )
    client = get_client(chroma_config.persistence_path)
    collection = open_or_create_collection(client, chroma_config, identity)

    embedder = FakeEmbeddingService(model_name=_MODEL_NAME)
    texts = ["control system overview", "wiring diagram details", "instrument tag table"]
    ids = ["chunk_1", "chunk_2", "chunk_3"]
    records, _stats = embedder.embed_passages(ids, texts)
    metadatas = [
        chroma_safe_metadata({"source_filename": "doc.pdf", "chunk_index": i, "content_type": "text"})
        for i in range(3)
    ]
    for m, t in zip(metadatas, texts, strict=True):
        m["content_hash"] = content_hash(t, m)
    ingest_batch(
        collection,
        ids=ids,
        embeddings=[r.vector for r in records],
        documents=texts,
        metadatas=metadatas,
        idempotent=True,
    )
    return chroma_config


def _config(tmp_path: Path, **overrides: object) -> RetrievalConfig:
    chroma_config = _build_indexed_collection(tmp_path)
    return RetrievalConfig(
        embedding={"model_name": _MODEL_NAME, "expected_dimension": 768},
        chroma=chroma_config,
        **overrides,  # type: ignore[arg-type]
    )


def _fake_embedder() -> FakeEmbeddingService:
    return FakeEmbeddingService(model_name=_MODEL_NAME)


class TestOpenCollectionReadonly:
    def test_missing_persistence_path_raises(self, tmp_path: Path) -> None:
        config = RetrievalConfig(chroma={"persistence_path": tmp_path / "does-not-exist"})
        with pytest.raises(CollectionNotFoundError):
            run_search("q", config, embedder=_fake_embedder())

    def test_missing_collection_raises(self, tmp_path: Path) -> None:
        chroma_config = _build_indexed_collection(tmp_path).model_copy(
            update={"collection_name": "does-not-exist"}
        )
        config = RetrievalConfig(embedding={"model_name": _MODEL_NAME}, chroma=chroma_config)
        with pytest.raises(CollectionNotFoundError):
            run_search("q", config, embedder=_fake_embedder())

    def test_never_creates_a_collection(self, tmp_path: Path) -> None:
        chroma_config = ChromaConfig(persistence_path=tmp_path / "chroma", collection_name="never-created")
        config = RetrievalConfig(embedding={"model_name": _MODEL_NAME}, chroma=chroma_config)
        with pytest.raises(CollectionNotFoundError):
            run_search("q", config, embedder=_fake_embedder())
        client = get_client(chroma_config.persistence_path)
        assert "never-created" not in {c.name for c in client.list_collections()}


class TestRunSearch:
    def test_returns_hits_with_provenance(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        response = run_search("control system overview", config, embedder=_fake_embedder(), top_k=2)
        assert response.returned_count == 2
        assert response.hits[0].source_filename == "doc.pdf"

    def test_search_never_mutates_the_collection(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        _client, collection = _open(config)
        before = collection.count()
        run_search("q", config, embedder=_fake_embedder())
        run_search("q2", config, embedder=_fake_embedder())
        assert collection.count() == before


def _open(config: RetrievalConfig) -> tuple[object, object]:
    from engineering_rag.pipelines.retrieval_pipeline import open_collection_readonly

    return open_collection_readonly(config)


class TestInspectCollection:
    def test_reports_count_and_identity(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        report = inspect_collection(config)
        assert report.exists is True
        assert report.count == 3
        assert report.distance_metric == "cosine"
        assert report.embedding_dimension == 768
        assert "doc.pdf" in report.source_filename_distribution

    def test_missing_collection_reports_exists_false(self, tmp_path: Path) -> None:
        chroma_config = ChromaConfig(persistence_path=tmp_path / "chroma", collection_name="nope")
        config = RetrievalConfig(chroma=chroma_config)
        report = inspect_collection(config)
        assert report.exists is False
        assert report.count == 0


class TestValidateEnvironment:
    def test_passes_for_a_compatible_collection(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        report = validate_environment(config)
        assert report.passed is True

    def test_fails_when_path_is_missing(self, tmp_path: Path) -> None:
        config = RetrievalConfig(chroma={"persistence_path": tmp_path / "nope"})
        report = validate_environment(config)
        assert report.passed is False
        assert report.checks[0]["check_id"] == "chroma_path_exists"

    def test_fails_when_model_name_does_not_match_profile(self, tmp_path: Path) -> None:
        chroma_config = _build_indexed_collection(tmp_path)
        config = RetrievalConfig(embedding={"model_name": "a-different-model"}, chroma=chroma_config)
        report = validate_environment(config)
        assert report.passed is False
        names = [c["check_id"] for c in report.checks if not c["passed"]]
        assert "model_name_matches_profile" in names


class TestRunEvaluationPipeline:
    def test_writes_all_expected_report_files(self, tmp_path: Path) -> None:
        chroma_config = _build_indexed_collection(tmp_path)
        dataset_path = tmp_path / "gt.jsonl"
        dataset_path.write_text(
            '{"case_id": "c1", "query": "control system overview", "query_type": "exact_term", '
            '"source_document": "doc.pdf", "relevant_chunk_ids": ["chunk_1"]}\n',
            encoding="utf-8",
        )
        config = RetrievalConfig(
            embedding={"model_name": _MODEL_NAME},
            chroma=chroma_config,
            evaluation={
                "dataset_path": str(dataset_path),
                "output_root": str(tmp_path / "out"),
                "k_values": [1, 3],
            },
        )
        run_dir, rows, summary = run_evaluation_pipeline(config, embedder=_fake_embedder())

        assert summary.case_count == 1
        assert len(rows) == 1
        for name in (
            "retrieval_results.jsonl",
            "retrieval_evaluation_report.json",
            "retrieval_evaluation_summary.md",
            "retrieval_manifest.json",
            "validation_report.json",
        ):
            assert (run_dir.root / name).is_file()

    def test_missing_dataset_raises_file_not_found(self, tmp_path: Path) -> None:
        chroma_config = _build_indexed_collection(tmp_path)
        config = RetrievalConfig(
            embedding={"model_name": _MODEL_NAME},
            chroma=chroma_config,
            evaluation={"dataset_path": str(tmp_path / "missing.jsonl")},
        )
        with pytest.raises(FileNotFoundError):
            run_evaluation_pipeline(config, embedder=_fake_embedder())

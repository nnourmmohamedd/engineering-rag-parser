"""CLI tests for ``engrag-retrieve``: exit codes, help, and delegation to the pipeline.

Every subcommand's happy path is exercised by monkeypatching the pipeline
function it calls, so this suite never downloads the real BGE model or opens
a real Chroma database — matching the CI-network-free convention used by
``test_index_cli.py``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import engineering_rag.api.retrieve_cli as cli_module
from engineering_rag.api.retrieve_cli import _resolve_toggles, app
from engineering_rag.databases.bm25.models import BM25Manifest
from engineering_rag.pipelines.retrieval_pipeline import InspectionReport, ValidationReport
from engineering_rag.services.retriever import (
    RETRIEVER_VERSION,
    CorpusCompatibilityError,
    InvalidFilterError,
    RetrievalError,
)
from engineering_rag.services.retriever.models import (
    RetrievalEvaluationSummary,
    RetrievalHit,
    RetrievalResponse,
)

runner = CliRunner()


def _write_profile(tmp_path: Path) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump({}), encoding="utf-8")
    return path


def _fake_response() -> RetrievalResponse:
    return RetrievalResponse(
        query="q",
        query_hash="abc123",
        collection_name="col",
        requested_top_k=1,
        returned_count=1,
        embedding_model="m",
        embedding_revision="rev",
        embedding_dimension=768,
        distance_metric="cosine",
        embedding_duration_s=0.01,
        database_duration_s=0.01,
        total_duration_s=0.02,
        hits=[
            RetrievalHit(
                rank=1,
                chunk_id="chunk_1",
                retrieval_text="hello world",
                raw_distance=0.1,
                similarity_score=0.9,
                source_filename="doc.pdf",
                page_numbers=[1],
                section_title="Intro",
            )
        ],
    )


class TestVersionAndHelp:
    def test_version(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert RETRIEVER_VERSION in result.stdout

    def test_no_args_shows_help(self) -> None:
        result = runner.invoke(app, [])
        assert "search" in result.output

    def test_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for cmd in ("search", "inspect", "validate", "evaluate"):
            assert cmd in result.output

    def test_search_help(self) -> None:
        result = runner.invoke(app, ["search", "--help"])
        assert result.exit_code == 0


class TestSearchCommand:
    def test_happy_path_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile = _write_profile(tmp_path)
        monkeypatch.setattr(cli_module, "run_hybrid_search", lambda *a, **kw: _fake_response())
        result = runner.invoke(app, ["search", "--query", "hello", "--profile", str(profile), "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["hits"][0]["chunk_id"] == "chunk_1"

    def test_happy_path_table_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile = _write_profile(tmp_path)
        monkeypatch.setattr(cli_module, "run_hybrid_search", lambda *a, **kw: _fake_response())
        result = runner.invoke(app, ["search", "--query", "hello", "--profile", str(profile)])
        assert result.exit_code == 0
        assert "chunk_1" in result.stdout

    def test_writes_output_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile = _write_profile(tmp_path)
        out_path = tmp_path / "out.json"
        monkeypatch.setattr(cli_module, "run_hybrid_search", lambda *a, **kw: _fake_response())
        result = runner.invoke(
            app, ["search", "--query", "hello", "--profile", str(profile), "--output", str(out_path)]
        )
        assert result.exit_code == 0
        assert out_path.is_file()
        assert json.loads(out_path.read_text(encoding="utf-8"))["hits"][0]["chunk_id"] == "chunk_1"

    def test_invalid_filter_syntax_is_rejected(self, tmp_path: Path) -> None:
        profile = _write_profile(tmp_path)
        result = runner.invoke(
            app, ["search", "--query", "hello", "--profile", str(profile), "--filter", "no-equals"]
        )
        assert result.exit_code != 0

    def test_invalid_filter_field_exits_2(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile = _write_profile(tmp_path)

        def _raise(*a: object, **kw: object) -> RetrievalResponse:
            raise InvalidFilterError("bad field")

        monkeypatch.setattr(cli_module, "run_hybrid_search", _raise)
        result = runner.invoke(app, ["search", "--query", "hello", "--profile", str(profile)])
        assert result.exit_code == 2

    def test_retrieval_error_exits_3(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile = _write_profile(tmp_path)

        def _raise(*a: object, **kw: object) -> RetrievalResponse:
            raise RetrievalError("collection empty")

        monkeypatch.setattr(cli_module, "run_hybrid_search", _raise)
        result = runner.invoke(app, ["search", "--query", "hello", "--profile", str(profile)])
        assert result.exit_code == 3


class TestInspectCommand:
    def test_existing_collection_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile = _write_profile(tmp_path)
        report = InspectionReport(
            chroma_path="path",
            collection_name="col",
            exists=True,
            count=10,
            distance_metric="cosine",
            embedding_dimension=768,
            sample_metadata_keys=["a", "b"],
            identity_metadata={"model_name": "m"},
            source_filename_distribution={"doc.pdf": 10},
        )
        monkeypatch.setattr(cli_module, "inspect_collection", lambda *a, **kw: report)
        result = runner.invoke(app, ["inspect", "--profile", str(profile), "--json"])
        assert result.exit_code == 0
        assert json.loads(result.stdout)["count"] == 10

    def test_missing_collection_exits_2(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile = _write_profile(tmp_path)
        report = InspectionReport(
            chroma_path="path",
            collection_name="col",
            exists=False,
            count=0,
            distance_metric="",
            embedding_dimension=None,
            sample_metadata_keys=[],
            identity_metadata={},
            source_filename_distribution={},
        )
        monkeypatch.setattr(cli_module, "inspect_collection", lambda *a, **kw: report)
        result = runner.invoke(app, ["inspect", "--profile", str(profile)])
        assert result.exit_code == 2


class TestValidateCommand:
    def test_pass_exits_0(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile = _write_profile(tmp_path)
        report = ValidationReport(checks=[{"check_id": "a", "passed": True, "summary": "ok"}])
        monkeypatch.setattr(cli_module, "validate_environment", lambda *a, **kw: report)
        result = runner.invoke(app, ["validate", "--profile", str(profile)])
        assert result.exit_code == 0

    def test_fail_exits_1(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile = _write_profile(tmp_path)
        report = ValidationReport(checks=[{"check_id": "a", "passed": False, "summary": "bad"}])
        monkeypatch.setattr(cli_module, "validate_environment", lambda *a, **kw: report)
        result = runner.invoke(app, ["validate", "--profile", str(profile)])
        assert result.exit_code == 1

    def test_json_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile = _write_profile(tmp_path)
        report = ValidationReport(checks=[{"check_id": "a", "passed": True, "summary": "ok"}])
        monkeypatch.setattr(cli_module, "validate_environment", lambda *a, **kw: report)
        result = runner.invoke(app, ["validate", "--profile", str(profile), "--json"])
        assert result.exit_code == 0
        assert json.loads(result.stdout)["status"] == "PASS"


class TestEvaluateCommand:
    def test_happy_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile = _write_profile(tmp_path)
        summary = RetrievalEvaluationSummary(
            run_id="run1",
            generated_at_utc=datetime.now(timezone.utc),
            dataset_path="d.jsonl",
            dataset_version="1",
            dataset_hash="h",
            k_values=[1, 3],
            case_count=2,
            positive_case_count=2,
            negative_case_count=0,
            human_reviewed_count=0,
            human_approved_count=0,
            collection_name="col",
            collection_count=2,
            distance_metric="cosine",
            embedding_model="m",
            embedding_revision=None,
            hit_rate_at_k={1: 1.0, 3: 1.0},
            recall_at_k={1: 1.0, 3: 1.0},
            precision_at_k={1: 1.0, 3: 0.33},
            mean_reciprocal_rank=1.0,
            ndcg_at_k={1: 1.0, 3: 1.0},
        )

        class _FakeRunDir:
            root = tmp_path / "run1"

        (tmp_path / "run1").mkdir()

        def _fake_run(
            *a: object, **kw: object
        ) -> tuple[_FakeRunDir, list[object], RetrievalEvaluationSummary]:
            return _FakeRunDir(), [], summary

        monkeypatch.setattr(cli_module, "run_evaluation_pipeline", _fake_run)
        result = runner.invoke(app, ["evaluate", "--profile", str(profile)])
        assert result.exit_code == 0
        assert "run1" in result.output

    def test_missing_dataset_exits_2(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile = _write_profile(tmp_path)

        def _raise(*a: object, **kw: object) -> object:
            raise FileNotFoundError("no dataset")

        monkeypatch.setattr(cli_module, "run_evaluation_pipeline", _raise)
        result = runner.invoke(app, ["evaluate", "--profile", str(profile)])
        assert result.exit_code == 2


class TestModeTogglePrecedence:
    """Explicit flags > --mode > profile — see `_resolve_toggles`'s docstring."""

    def test_profile_only(self) -> None:
        bm25, rerank, _ = _resolve_toggles(
            profile_bm25=False, profile_reranker=False, mode=None, bm25_flag=None, rerank_flag=None
        )
        assert (bm25, rerank) == (False, False)

    def test_mode_overrides_profile(self) -> None:
        bm25, rerank, _ = _resolve_toggles(
            profile_bm25=False, profile_reranker=False, mode="hybrid-rerank", bm25_flag=None, rerank_flag=None
        )
        assert (bm25, rerank) == (True, True)

    def test_explicit_flag_overrides_mode(self) -> None:
        bm25, rerank, _ = _resolve_toggles(
            profile_bm25=False,
            profile_reranker=False,
            mode="hybrid-rerank",
            bm25_flag=False,
            rerank_flag=None,
        )
        assert (bm25, rerank) == (False, True)

    def test_explicit_flags_override_everything(self) -> None:
        bm25, rerank, _ = _resolve_toggles(
            profile_bm25=True, profile_reranker=True, mode="vector", bm25_flag=True, rerank_flag=True
        )
        assert (bm25, rerank) == (True, True)

    def test_vector_rerank_mode(self) -> None:
        bm25, rerank, _ = _resolve_toggles(
            profile_bm25=False, profile_reranker=False, mode="vector-rerank", bm25_flag=None, rerank_flag=None
        )
        assert (bm25, rerank) == (False, True)


class TestSearchModeFlags:
    def test_invalid_mode_exits_2(self, tmp_path: Path) -> None:
        profile = _write_profile(tmp_path)
        result = runner.invoke(
            app, ["search", "--query", "hello", "--profile", str(profile), "--mode", "bogus"]
        )
        assert result.exit_code == 2

    def test_mode_hybrid_is_forwarded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile = _write_profile(tmp_path)
        captured: dict[str, object] = {}

        def _fake(*a: object, **kw: object) -> RetrievalResponse:
            captured.update(kw)
            return _fake_response()

        monkeypatch.setattr(cli_module, "run_hybrid_search", _fake)
        result = runner.invoke(
            app, ["search", "--query", "hello", "--profile", str(profile), "--mode", "hybrid"]
        )
        assert result.exit_code == 0
        assert captured["bm25_enabled"] is True
        assert captured["reranker_enabled"] is False

    def test_no_bm25_flag_overrides_mode(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile = _write_profile(tmp_path)
        captured: dict[str, object] = {}

        def _fake(*a: object, **kw: object) -> RetrievalResponse:
            captured.update(kw)
            return _fake_response()

        monkeypatch.setattr(cli_module, "run_hybrid_search", _fake)
        result = runner.invoke(
            app,
            ["search", "--query", "hello", "--profile", str(profile), "--mode", "hybrid", "--no-bm25"],
        )
        assert result.exit_code == 0
        assert captured["bm25_enabled"] is False

    def test_corpus_compatibility_error_exits_5(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile = _write_profile(tmp_path)

        def _raise(*a: object, **kw: object) -> RetrievalResponse:
            raise CorpusCompatibilityError("mismatch")

        monkeypatch.setattr(cli_module, "run_hybrid_search", _raise)
        result = runner.invoke(
            app, ["search", "--query", "hello", "--profile", str(profile), "--mode", "hybrid"]
        )
        assert result.exit_code == 5


class TestBuildBm25Command:
    def _manifest(self) -> BM25Manifest:
        from datetime import datetime, timezone

        return BM25Manifest(
            generated_at_utc=datetime.now(timezone.utc),
            collection_name="col",
            chroma_persistence_path="path",
            corpus_count=3,
            corpus_fingerprint="abc123",
            chunk_ids=["c1", "c2", "c3"],
            bm25_library="bm25s",
            bm25_library_version="0.3.11",
            tokenizer_version="1.0.0",
            method="lucene",
            k1=1.2,
            b=0.75,
        )

    def test_happy_path_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile = _write_profile(tmp_path)
        manifest = self._manifest()
        monkeypatch.setattr(cli_module, "build_bm25_index_pipeline", lambda *a, **kw: manifest)
        result = runner.invoke(app, ["build-bm25", "--profile", str(profile), "--json"])
        assert result.exit_code == 0
        assert json.loads(result.stdout)["corpus_count"] == 3

    def test_help(self) -> None:
        result = runner.invoke(app, ["build-bm25", "--help"])
        assert result.exit_code == 0

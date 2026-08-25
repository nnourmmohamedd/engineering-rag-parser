"""CLI tests for ``engrag-ask``: exit codes, help, and delegation to the pipeline.

Every subcommand's happy path is exercised by monkeypatching the pipeline
function it calls, so this suite never opens a real Chroma database, never
downloads a real model, and never requires a real Ollama server -- matching
the CI-network-free convention used by ``test_retrieve_cli.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import engineering_rag.api.ask_cli as cli_module
from engineering_rag.api.ask_cli import app
from engineering_rag.pipelines.answering_evaluation import AnsweringEvaluationSummary
from engineering_rag.pipelines.answering_pipeline import (
    AnsweringValidationReport,
    OllamaEnvironmentReport,
    RetrievalValidationReport,
)
from engineering_rag.services.answerer import ANSWERER_VERSION, AnswerResponse
from engineering_rag.services.context_builder.models import ContextPackage, SelectedSource
from engineering_rag.services.grounding import GroundingReport
from engineering_rag.services.retriever import CorpusCompatibilityError, RetrievalError

runner = CliRunner()


def _write_yaml(tmp_path: Path, name: str, data: dict[str, object] | None = None) -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data or {}), encoding="utf-8")
    return path


def _profiles(tmp_path: Path) -> tuple[Path, Path]:
    return _write_yaml(tmp_path, "answering.yaml"), _write_yaml(tmp_path, "retrieval.yaml")


def _source() -> SelectedSource:
    return SelectedSource(
        citation_id="S1",
        chunk_id="c1",
        document_id="d1",
        retrieval_text="FEED develops the control philosophy.",
        source_filename="doc.pdf",
        page_numbers=[3],
        selection_order=1,
        token_count=10,
    )


def _fake_context() -> ContextPackage:
    return ContextPackage(
        query="q",
        query_hash="h",
        retrieval_mode="vector",
        selected_sources=[_source()],
        excluded_candidates=[],
        total_candidates_received=1,
        total_sources_selected=1,
        context_token_count=10,
        token_budget=5000,
        reserved_output_tokens=1024,
        prompt_overhead_tokens=1300,
        context_text='<SOURCE id="S1">FEED develops the control philosophy.</SOURCE>',
    )


def _fake_answer() -> AnswerResponse:
    return AnswerResponse(
        run_id="run1",
        query="q",
        query_hash="h",
        answer="FEED develops the control philosophy [S1].",
        status="answered",
        insufficient_evidence=False,
        citations=[],
        retrieval_mode="vector",
        context_token_count=10,
        token_budget=5000,
        model_tag="qwen3:8b",
        model_digest="abc",
        prompt_version="1.0.0",
        validation=GroundingReport(status="PASS"),
        generated_at_utc=datetime.now(timezone.utc),
    )


class TestTopLevel:
    def test_version(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert ANSWERER_VERSION in result.stdout

    def test_no_args_shows_help(self) -> None:
        result = runner.invoke(app, [])
        assert "ask" in result.output

    def test_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    def test_ask_help(self) -> None:
        result = runner.invoke(app, ["ask", "--help"])
        assert result.exit_code == 0

    def test_context_help(self) -> None:
        result = runner.invoke(app, ["context", "--help"])
        assert result.exit_code == 0

    def test_validate_help(self) -> None:
        result = runner.invoke(app, ["validate", "--help"])
        assert result.exit_code == 0

    def test_evaluate_help(self) -> None:
        result = runner.invoke(app, ["evaluate", "--help"])
        assert result.exit_code == 0


class TestValidateCommand:
    def test_validate_never_generates_and_reports_pass(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile, retrieval_profile = _profiles(tmp_path)
        report = AnsweringValidationReport(
            ollama=OllamaEnvironmentReport(
                checks=[{"check_id": "ollama_reachable", "passed": True, "summary": "ok"}]
            ),
            retrieval=RetrievalValidationReport(
                checks=[{"check_id": "collection_exists", "passed": True, "summary": "ok"}]
            ),
            config_checks=[{"check_id": "token_budget_fits_context_window", "passed": True, "summary": "ok"}],
        )
        called = {"n": 0}

        def fake_validate_all(*a: object, **kw: object) -> AnsweringValidationReport:
            called["n"] += 1
            return report

        monkeypatch.setattr(cli_module, "validate_all", fake_validate_all)
        result = runner.invoke(
            app, ["validate", "--profile", str(profile), "--retrieval-profile", str(retrieval_profile)]
        )
        assert result.exit_code == 0
        assert called["n"] == 1

    def test_validate_json_and_nonzero_exit_on_fail(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile, retrieval_profile = _profiles(tmp_path)
        report = AnsweringValidationReport(
            ollama=OllamaEnvironmentReport(
                checks=[{"check_id": "ollama_reachable", "passed": False, "summary": "down"}]
            ),
            retrieval=RetrievalValidationReport(checks=[]),
            config_checks=[],
        )
        monkeypatch.setattr(cli_module, "validate_all", lambda *a, **kw: report)
        result = runner.invoke(
            app,
            ["validate", "--profile", str(profile), "--retrieval-profile", str(retrieval_profile), "--json"],
        )
        assert result.exit_code == 1
        assert '"status": "FAIL"' in result.stdout


class TestContextCommand:
    def test_context_never_calls_llm(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile, retrieval_profile = _profiles(tmp_path)
        called = {"context": 0, "ask": 0}

        def fake_context(*a: object, **kw: object) -> tuple[None, ContextPackage]:
            called["context"] += 1
            return None, _fake_context()

        def fake_ask(*a: object, **kw: object) -> None:
            called["ask"] += 1
            raise AssertionError("context command must never call the LLM/ask pipeline")

        monkeypatch.setattr(cli_module, "run_context_pipeline", fake_context)
        monkeypatch.setattr(cli_module, "run_ask_pipeline", fake_ask)
        result = runner.invoke(
            app,
            [
                "context",
                "--query",
                "q",
                "--profile",
                str(profile),
                "--retrieval-profile",
                str(retrieval_profile),
            ],
        )
        assert result.exit_code == 0
        assert called["context"] == 1
        assert called["ask"] == 0

    def test_context_json_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile, retrieval_profile = _profiles(tmp_path)
        monkeypatch.setattr(cli_module, "run_context_pipeline", lambda *a, **kw: (None, _fake_context()))
        result = runner.invoke(
            app,
            [
                "context",
                "--query",
                "q",
                "--profile",
                str(profile),
                "--retrieval-profile",
                str(retrieval_profile),
                "--json",
            ],
        )
        assert result.exit_code == 0
        assert '"context_schema_version"' in result.stdout

    def test_context_file_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile, retrieval_profile = _profiles(tmp_path)
        monkeypatch.setattr(cli_module, "run_context_pipeline", lambda *a, **kw: (None, _fake_context()))
        out = tmp_path / "context.json"
        result = runner.invoke(
            app,
            [
                "context",
                "--query",
                "q",
                "--profile",
                str(profile),
                "--retrieval-profile",
                str(retrieval_profile),
                "--output",
                str(out),
            ],
        )
        assert result.exit_code == 0
        assert out.is_file()

    def test_context_invalid_profile_path(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["context", "--query", "q", "--profile", str(tmp_path / "missing.yaml")])
        assert result.exit_code != 0

    def test_corpus_compatibility_error_maps_to_exit_5(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile, retrieval_profile = _profiles(tmp_path)

        def _raise(*a: object, **kw: object) -> None:
            raise CorpusCompatibilityError("mismatch")

        monkeypatch.setattr(cli_module, "run_context_pipeline", _raise)
        result = runner.invoke(
            app,
            [
                "context",
                "--query",
                "q",
                "--profile",
                str(profile),
                "--retrieval-profile",
                str(retrieval_profile),
            ],
        )
        assert result.exit_code == 5


class TestAskCommand:
    def test_ask_all_modes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile, retrieval_profile = _profiles(tmp_path)
        monkeypatch.setattr(
            cli_module,
            "run_ask_pipeline",
            lambda *a, **kw: (None, _fake_context(), _fake_answer(), None, None),
        )
        for mode in ("vector", "hybrid", "vector-rerank", "hybrid-rerank"):
            result = runner.invoke(
                app,
                [
                    "ask",
                    "--query",
                    "q",
                    "--profile",
                    str(profile),
                    "--retrieval-profile",
                    str(retrieval_profile),
                    "--retrieval-mode",
                    mode,
                ],
            )
            assert result.exit_code == 0, result.stdout
            assert "ANSWERED" in result.stdout

    def test_ask_json_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile, retrieval_profile = _profiles(tmp_path)
        monkeypatch.setattr(
            cli_module,
            "run_ask_pipeline",
            lambda *a, **kw: (None, _fake_context(), _fake_answer(), None, None),
        )
        result = runner.invoke(
            app,
            [
                "ask",
                "--query",
                "q",
                "--profile",
                str(profile),
                "--retrieval-profile",
                str(retrieval_profile),
                "--json",
            ],
        )
        assert result.exit_code == 0
        assert '"answer_schema_version"' in result.stdout

    def test_ask_file_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile, retrieval_profile = _profiles(tmp_path)
        monkeypatch.setattr(
            cli_module,
            "run_ask_pipeline",
            lambda *a, **kw: (None, _fake_context(), _fake_answer(), None, None),
        )
        out = tmp_path / "answer.json"
        result = runner.invoke(
            app,
            [
                "ask",
                "--query",
                "q",
                "--profile",
                str(profile),
                "--retrieval-profile",
                str(retrieval_profile),
                "--output",
                str(out),
            ],
        )
        assert result.exit_code == 0
        assert out.is_file()

    def test_ask_never_leaks_hidden_prompt_in_normal_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile, retrieval_profile = _profiles(tmp_path)
        monkeypatch.setattr(
            cli_module,
            "run_ask_pipeline",
            lambda *a, **kw: (None, _fake_context(), _fake_answer(), None, None),
        )
        result = runner.invoke(
            app,
            ["ask", "--query", "q", "--profile", str(profile), "--retrieval-profile", str(retrieval_profile)],
        )
        assert "Sources contain" not in result.stdout  # a system-prompt phrase must never leak

    def test_ollama_unavailable_maps_to_exit_6(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from engineering_rag.clients.ollama import OllamaConnectionError

        profile, retrieval_profile = _profiles(tmp_path)

        def _raise(*a: object, **kw: object) -> None:
            raise OllamaConnectionError("refused")

        monkeypatch.setattr(cli_module, "run_ask_pipeline", _raise)
        result = runner.invoke(
            app,
            ["ask", "--query", "q", "--profile", str(profile), "--retrieval-profile", str(retrieval_profile)],
        )
        assert result.exit_code == 6

    def test_retrieval_error_maps_to_exit_3(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile, retrieval_profile = _profiles(tmp_path)

        def _raise(*a: object, **kw: object) -> None:
            raise RetrievalError("boom")

        monkeypatch.setattr(cli_module, "run_ask_pipeline", _raise)
        result = runner.invoke(
            app,
            ["ask", "--query", "q", "--profile", str(profile), "--retrieval-profile", str(retrieval_profile)],
        )
        assert result.exit_code == 3

    def test_invalid_retrieval_mode_rejected(self, tmp_path: Path) -> None:
        profile, retrieval_profile = _profiles(tmp_path)
        result = runner.invoke(
            app,
            [
                "ask",
                "--query",
                "q",
                "--profile",
                str(profile),
                "--retrieval-profile",
                str(retrieval_profile),
                "--retrieval-mode",
                "bogus",
            ],
        )
        assert result.exit_code == 2


class TestEvaluateCommand:
    def test_evaluate_delegates_and_prints_summary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile, retrieval_profile = _profiles(tmp_path)
        summary = AnsweringEvaluationSummary(
            run_id="run1",
            generated_at_utc=datetime.now(timezone.utc),
            dataset_path="data/eval/answering_ground_truth.jsonl",
            dataset_hash="abc",
            case_count=1,
            retrieval_mode="vector",
            structured_output_validity_rate=1.0,
            answer_or_refusal_success_rate=1.0,
            refusal_precision=None,
            refusal_recall=None,
            citation_validity_rate=1.0,
            unknown_citation_rate=0.0,
            supporting_quote_validity_rate=1.0,
            mean_citation_coverage=1.0,
            expected_source_precision=None,
            expected_source_recall=None,
            context_budget_compliance_rate=1.0,
            artifact_completeness_rate=1.0,
            generation_failure_rate=0.0,
            grounding_pass_rate=1.0,
            latency_p50_s=0.1,
            latency_p95_s=0.2,
            mean_prompt_token_count=100.0,
            mean_answer_token_count=20.0,
        )

        class _FakeRunDir:
            root = tmp_path / "run1"

        monkeypatch.setattr(
            cli_module, "run_answering_evaluation", lambda *a, **kw: (_FakeRunDir(), [], summary)
        )
        result = runner.invoke(
            app, ["evaluate", "--profile", str(profile), "--retrieval-profile", str(retrieval_profile)]
        )
        assert result.exit_code == 0
        assert "Answering evaluation run" in result.stdout

    def test_evaluate_missing_dataset_exits_2(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        profile, retrieval_profile = _profiles(tmp_path)

        def _raise(*a: object, **kw: object) -> None:
            raise FileNotFoundError("no dataset")

        monkeypatch.setattr(cli_module, "run_answering_evaluation", _raise)
        result = runner.invoke(
            app, ["evaluate", "--profile", str(profile), "--retrieval-profile", str(retrieval_profile)]
        )
        assert result.exit_code == 2

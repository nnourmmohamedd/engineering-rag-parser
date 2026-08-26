from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import engineering_rag.pipelines.answering_evaluation as evaluation_module
from engineering_rag.pipelines.answering_config import AnsweringPipelineConfig
from engineering_rag.pipelines.answering_evaluation import (
    AnsweringEvaluationCase,
    load_answering_evaluation_dataset,
    run_answering_evaluation,
)
from engineering_rag.pipelines.retrieval_config import RetrievalConfig
from engineering_rag.services.answerer import AnswerResponse
from engineering_rag.services.context_builder.models import ContextPackage, SelectedSource
from engineering_rag.services.grounding import GroundingReport


def _write_dataset(tmp_path: Path, cases: list[dict[str, object]]) -> Path:
    path = tmp_path / "answering_ground_truth.jsonl"
    path.write_text("\n".join(json.dumps(c) for c in cases) + "\n", encoding="utf-8")
    return path


def _case(**overrides: object) -> dict[str, object]:
    base = {
        "case_id": "A001",
        "query": "What does FEED develop?",
        "case_type": "answerable",
        "expected_answerability": True,
        "expected_refusal": False,
        "expected_source_filenames": ["doc.pdf"],
    }
    base.update(overrides)
    return base


def _context() -> ContextPackage:
    return ContextPackage(
        query="q",
        query_hash="h",
        retrieval_mode="vector",
        selected_sources=[
            SelectedSource(
                citation_id="S1",
                chunk_id="c1",
                retrieval_text="FEED develops the control philosophy.",
                source_filename="doc.pdf",
                selection_order=1,
                token_count=10,
            )
        ],
        context_token_count=10,
        token_budget=5000,
        reserved_output_tokens=1024,
        prompt_overhead_tokens=1300,
        context_text="x",
    )


class _FakeRunDir:
    def __init__(self, root: Path) -> None:
        self.root = root


def _answer(*, status: str, source_filename: str | None = "doc.pdf") -> AnswerResponse:
    from engineering_rag.services.answerer import CitationSummary

    citations = (
        [CitationSummary(citation_id="S1", chunk_id="c1", source_filename=source_filename)]
        if status == "answered"
        else []
    )
    return AnswerResponse(
        run_id="r1",
        query="q",
        query_hash="h",
        answer="answer text [S1]." if status == "answered" else "refused",
        status=status,  # type: ignore[arg-type]
        insufficient_evidence=(status == "insufficient_evidence"),
        citations=citations,
        retrieval_mode="vector",
        context_token_count=10,
        token_budget=5000,
        prompt_token_count=100,
        answer_token_count=20,
        model_tag="qwen3:8b",
        prompt_version="1.0.0",
        validation=GroundingReport(status="PASS" if status == "answered" else "FAIL"),
        total_latency_s=0.5,
        generated_at_utc=datetime.now(timezone.utc),
    )


class TestLoadDataset:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_answering_evaluation_dataset(tmp_path / "missing.jsonl")

    def test_empty_file_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="empty"):
            load_answering_evaluation_dataset(path)

    def test_loads_valid_cases(self, tmp_path: Path) -> None:
        path = _write_dataset(tmp_path, [_case()])
        cases = load_answering_evaluation_dataset(path)
        assert len(cases) == 1
        assert isinstance(cases[0], AnsweringEvaluationCase)


class TestRunAnsweringEvaluation:
    def test_correct_answer_and_refusal_scored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        dataset_path = _write_dataset(
            tmp_path,
            [
                _case(case_id="A001", expected_refusal=False),
                _case(
                    case_id="A002",
                    query="unanswerable?",
                    case_type="unanswerable",
                    expected_answerability=False,
                    expected_refusal=True,
                    expected_source_filenames=[],
                ),
            ],
        )
        answering_config = AnsweringPipelineConfig(
            evaluation={"dataset_path": dataset_path, "output_root": tmp_path / "out"}
        )
        retrieval_config = RetrievalConfig()

        run_root = tmp_path / "run"
        run_root.mkdir(exist_ok=True)

        def fake_run_ask_pipeline(query: str, *a: object, **kw: object):
            fake_run_dir = _FakeRunDir(run_root)
            if "unanswerable" in query:
                return None, _context(), _answer(status="insufficient_evidence"), None, fake_run_dir
            return None, _context(), _answer(status="answered"), None, fake_run_dir

        monkeypatch.setattr(evaluation_module, "run_ask_pipeline", fake_run_ask_pipeline)
        run_dir, results, summary = run_answering_evaluation(
            answering_config, retrieval_config, retrieval_mode="vector"
        )

        assert summary.case_count == 2
        assert summary.answer_or_refusal_success_rate == 1.0
        assert summary.refusal_precision == 1.0
        assert summary.refusal_recall == 1.0
        assert (run_dir.root / "answering_evaluation_report.json").is_file()
        assert (run_dir.root / "answering_evaluation_summary.md").is_file()
        assert len(results) == 2

    def test_case_exception_does_not_abort_whole_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dataset_path = _write_dataset(tmp_path, [_case(case_id="A001"), _case(case_id="A002")])
        answering_config = AnsweringPipelineConfig(
            evaluation={"dataset_path": dataset_path, "output_root": tmp_path / "out"}
        )
        retrieval_config = RetrievalConfig()

        calls = {"n": 0}

        run_root = tmp_path / "run"
        run_root.mkdir(exist_ok=True)

        def flaky(query: str, *a: object, **kw: object):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return None, _context(), _answer(status="answered"), None, _FakeRunDir(run_root)

        monkeypatch.setattr(evaluation_module, "run_ask_pipeline", flaky)
        _run_dir, results, summary = run_answering_evaluation(
            answering_config, retrieval_config, retrieval_mode="vector"
        )
        assert summary.case_count == 2
        assert results[0].status == "generation_failed"
        assert results[0].warnings

    def test_missing_dataset_raises(self, tmp_path: Path) -> None:
        answering_config = AnsweringPipelineConfig(
            evaluation={"dataset_path": tmp_path / "missing.jsonl", "output_root": tmp_path / "out"}
        )
        with pytest.raises(FileNotFoundError):
            run_answering_evaluation(answering_config, RetrievalConfig(), retrieval_mode="vector")

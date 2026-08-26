"""Answering evaluation: a separate, versioned ground-truth dataset from retrieval's.

Retrieval's ``data/eval/retrieval_ground_truth.jsonl`` asks "did the right
chunks come back?". This dataset asks a different question: "did the final
*answer* refuse or cite correctly, and does it pass deterministic grounding
validation?". Every case runs the full :func:`~.answering_pipeline.run_ask_pipeline`
(real retrieval, real context building; real Ollama generation unless a fake
``LLMClient`` is injected) and every metric here is deterministic and
automated -- see ``docs/answering/EVALUATION.md`` for what is and is not
proven by a high score, and for the separate, still-pending human semantic
review of ``expected_key_facts``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from engineering_rag.clients.ollama import LLMClient
from engineering_rag.pipelines.answering_artifacts import AnsweringRunDirectory
from engineering_rag.pipelines.answering_config import AnsweringPipelineConfig
from engineering_rag.pipelines.answering_pipeline import run_ask_pipeline
from engineering_rag.pipelines.retrieval_config import RetrievalConfig

__all__ = [
    "AnsweringEvaluationCase",
    "AnsweringEvaluationResult",
    "AnsweringEvaluationSummary",
    "dataset_hash",
    "load_answering_evaluation_dataset",
    "run_answering_evaluation",
]

logger = logging.getLogger(__name__)

_REQUIRED_ARTIFACT_FILES = (
    "query.json",
    "retrieval_response.json",
    "context.json",
    "prompt_manifest.json",
    "answer_draft.json",
    "answer.json",
    "grounding_report.json",
    "manifest.json",
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnsweringEvaluationCase(_Model):
    """One ground-truth case for the answering evaluation dataset. Honestly labeled -- see module docstring."""

    case_id: str
    query: str
    case_type: Literal[
        "answerable",
        "exact_identifier",
        "multi_source_synthesis",
        "ocr",
        "unanswerable",
        "prompt_injection",
        "insufficient_evidence",
    ]
    expected_answerability: bool = Field(description="True if the indexed corpus should support an answer.")
    expected_refusal: bool = Field(description="True if a correct system should refuse this question.")
    expected_source_filenames: list[str] = Field(default_factory=list)
    expected_chunk_ids: list[str] = Field(default_factory=list)
    expected_key_facts: list[str] = Field(
        default_factory=list, description="Not automatically scored -- input to the pending human review."
    )
    label_status: Literal["machine_candidate", "human_reviewed", "human_approved"] = "machine_candidate"
    notes: str = ""


class AnsweringEvaluationResult(_Model):
    """Per-case, fully deterministic evaluation outcome."""

    case_id: str
    query: str
    case_type: str
    status: str
    expected_refusal: bool
    predicted_refusal: bool
    refusal_correct: bool
    grounding_status: str
    unknown_citation_count: int
    supporting_quote_valid_count: int
    supporting_quote_total_count: int
    citation_coverage_ratio: float | None
    expected_source_precision: float | None
    expected_source_recall: float | None
    context_budget_compliant: bool
    artifact_complete: bool
    prompt_token_count: int | None
    answer_token_count: int | None
    latency_s: float
    warnings: list[str] = Field(default_factory=list)


class AnsweringEvaluationSummary(_Model):
    """Aggregate, deterministic metrics over one evaluation run. See module docstring for scope."""

    run_id: str
    generated_at_utc: datetime
    dataset_path: str
    dataset_hash: str
    case_count: int
    retrieval_mode: str

    structured_output_validity_rate: float
    answer_or_refusal_success_rate: float
    refusal_precision: float | None
    refusal_recall: float | None
    citation_validity_rate: float
    unknown_citation_rate: float
    supporting_quote_validity_rate: float | None
    mean_citation_coverage: float | None
    expected_source_precision: float | None
    expected_source_recall: float | None
    context_budget_compliance_rate: float
    artifact_completeness_rate: float
    generation_failure_rate: float
    grounding_pass_rate: float

    latency_p50_s: float
    latency_p95_s: float
    mean_prompt_token_count: float | None
    mean_answer_token_count: float | None

    reproduction_command: str = ""
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Deterministic automated validation only: structural citation/quote checks, never a "
            "semantic-correctness or hallucination-free proof.",
            "expected_key_facts is a machine_candidate label, not yet human-reviewed -- see the human-review "
            "worksheet.",
        ]
    )


def dataset_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_answering_evaluation_dataset(path: Path) -> list[AnsweringEvaluationCase]:
    """Raises FileNotFoundError / ValueError on a missing or empty dataset."""
    if not path.is_file():
        raise FileNotFoundError(f"Answering evaluation dataset not found: {path}")
    cases: list[AnsweringEvaluationCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        cases.append(AnsweringEvaluationCase.model_validate(json.loads(stripped)))
    if not cases:
        raise ValueError(f"Answering evaluation dataset is empty: {path}")
    return cases


def _precision_recall(predicted: set[str], expected: set[str]) -> tuple[float | None, float | None]:
    if not expected:
        return None, None
    precision = len(predicted & expected) / len(predicted) if predicted else 0.0
    recall = len(predicted & expected) / len(expected)
    return precision, recall


def _evaluate_case(
    case: AnsweringEvaluationCase,
    answering_config: AnsweringPipelineConfig,
    retrieval_config: RetrievalConfig,
    *,
    retrieval_mode: str,
    llm_client: LLMClient | None,
) -> AnsweringEvaluationResult:
    warnings: list[str] = []
    started = time.perf_counter()
    try:
        _retrieval_response, context, answer_response, _trace, run_dir = run_ask_pipeline(
            case.query,
            answering_config,
            retrieval_config,
            retrieval_mode=retrieval_mode,
            llm_client=llm_client,
        )
    except Exception as exc:  # noqa: BLE001 - one bad case must not abort the whole evaluation run
        warnings.append(f"case failed with {type(exc).__name__}: {exc}")
        return AnsweringEvaluationResult(
            case_id=case.case_id,
            query=case.query,
            case_type=case.case_type,
            status="generation_failed",
            expected_refusal=case.expected_refusal,
            predicted_refusal=False,
            refusal_correct=False,
            grounding_status="FAIL",
            unknown_citation_count=0,
            supporting_quote_valid_count=0,
            supporting_quote_total_count=0,
            citation_coverage_ratio=None,
            expected_source_precision=None,
            expected_source_recall=None,
            context_budget_compliant=False,
            artifact_complete=False,
            prompt_token_count=None,
            answer_token_count=None,
            latency_s=round(time.perf_counter() - started, 4),
            warnings=warnings,
        )

    predicted_refusal = answer_response.status == "insufficient_evidence"
    refusal_correct = predicted_refusal == case.expected_refusal

    report = answer_response.validation
    quote_checks = report.quote_checks
    supporting_quote_valid_count = sum(1 for q in quote_checks if q.found_normalized)

    predicted_sources = {c.source_filename for c in answer_response.citations if c.source_filename}
    expected_sources = set(case.expected_source_filenames)
    src_precision, src_recall = _precision_recall(predicted_sources, expected_sources)

    context_budget_compliant = (
        context.context_token_count <= context.token_budget + context.prompt_overhead_tokens
    )
    artifact_complete = run_dir is not None and all(
        (run_dir.root / name).is_file() for name in _REQUIRED_ARTIFACT_FILES
    )

    return AnsweringEvaluationResult(
        case_id=case.case_id,
        query=case.query,
        case_type=case.case_type,
        status=answer_response.status,
        expected_refusal=case.expected_refusal,
        predicted_refusal=predicted_refusal,
        refusal_correct=refusal_correct,
        grounding_status=report.status,
        unknown_citation_count=len(report.unknown_citations),
        supporting_quote_valid_count=supporting_quote_valid_count,
        supporting_quote_total_count=len(quote_checks),
        citation_coverage_ratio=report.citation_coverage_ratio,
        expected_source_precision=src_precision,
        expected_source_recall=src_recall,
        context_budget_compliant=context_budget_compliant,
        artifact_complete=artifact_complete,
        prompt_token_count=answer_response.prompt_token_count,
        answer_token_count=answer_response.answer_token_count,
        latency_s=answer_response.total_latency_s,
        warnings=warnings,
    )


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct * (len(ordered) - 1))))
    return ordered[index]


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def run_answering_evaluation(
    answering_config: AnsweringPipelineConfig,
    retrieval_config: RetrievalConfig,
    *,
    retrieval_mode: str,
    llm_client: LLMClient | None = None,
    reproduction_command: str = "engrag-ask evaluate",
) -> tuple[AnsweringRunDirectory, list[AnsweringEvaluationResult], AnsweringEvaluationSummary]:
    """Run every case in the answering ground-truth dataset and write a full report.

    Raises:
        FileNotFoundError: the dataset does not exist.
        ValueError: the dataset is empty or malformed.
    """
    started = time.perf_counter()
    dataset_path = Path(answering_config.evaluation.dataset_path)
    cases = load_answering_evaluation_dataset(dataset_path)
    d_hash = dataset_hash(dataset_path)

    results = [
        _evaluate_case(
            case, answering_config, retrieval_config, retrieval_mode=retrieval_mode, llm_client=llm_client
        )
        for case in cases
    ]

    n = len(results)
    structured_ok = sum(1 for r in results if r.status != "generation_failed")
    refusal_correct = sum(1 for r in results if r.refusal_correct)
    expected_refusals = sum(1 for r in results if r.expected_refusal)
    predicted_refusals = sum(1 for r in results if r.predicted_refusal)
    true_positive_refusals = sum(1 for r in results if r.predicted_refusal and r.expected_refusal)
    answered_results = [r for r in results if r.status == "answered"]
    generation_failed = sum(1 for r in results if r.status == "generation_failed")
    grounding_pass = sum(1 for r in results if r.grounding_status in ("PASS", "PASS_WITH_WARNINGS"))
    context_budget_ok = sum(1 for r in results if r.context_budget_compliant)
    artifacts_ok = sum(1 for r in results if r.artifact_complete)

    total_quotes = sum(r.supporting_quote_total_count for r in results)
    valid_quotes = sum(r.supporting_quote_valid_count for r in results)

    coverage_values = [
        r.citation_coverage_ratio for r in answered_results if r.citation_coverage_ratio is not None
    ]
    src_precisions = [r.expected_source_precision for r in results if r.expected_source_precision is not None]
    src_recalls = [r.expected_source_recall for r in results if r.expected_source_recall is not None]
    latencies = [r.latency_s for r in results]
    prompt_tokens = [float(r.prompt_token_count) for r in results if r.prompt_token_count is not None]
    answer_tokens = [float(r.answer_token_count) for r in results if r.answer_token_count is not None]

    summary = AnsweringEvaluationSummary(
        run_id="",  # filled after run_dir creation, below
        generated_at_utc=datetime.now(timezone.utc),
        dataset_path=str(dataset_path),
        dataset_hash=d_hash,
        case_count=n,
        retrieval_mode=retrieval_mode,
        structured_output_validity_rate=structured_ok / n if n else 0.0,
        answer_or_refusal_success_rate=refusal_correct / n if n else 0.0,
        refusal_precision=(true_positive_refusals / predicted_refusals) if predicted_refusals else None,
        refusal_recall=(true_positive_refusals / expected_refusals) if expected_refusals else None,
        citation_validity_rate=(
            sum(1 for r in answered_results if r.unknown_citation_count == 0) / len(answered_results)
            if answered_results
            else 1.0
        ),
        unknown_citation_rate=(
            sum(1 for r in answered_results if r.unknown_citation_count > 0) / len(answered_results)
            if answered_results
            else 0.0
        ),
        supporting_quote_validity_rate=(valid_quotes / total_quotes) if total_quotes else None,
        mean_citation_coverage=_mean(coverage_values),
        expected_source_precision=_mean(src_precisions),
        expected_source_recall=_mean(src_recalls),
        context_budget_compliance_rate=context_budget_ok / n if n else 0.0,
        artifact_completeness_rate=artifacts_ok / n if n else 0.0,
        generation_failure_rate=generation_failed / n if n else 0.0,
        grounding_pass_rate=grounding_pass / n if n else 0.0,
        latency_p50_s=_percentile(latencies, 0.50),
        latency_p95_s=_percentile(latencies, 0.95),
        mean_prompt_token_count=_mean(prompt_tokens),
        mean_answer_token_count=_mean(answer_tokens),
        reproduction_command=reproduction_command,
    )

    run = AnsweringRunDirectory.create(Path(answering_config.evaluation.output_root))
    summary = summary.model_copy(update={"run_id": run.root.name})
    result_rows = [r.model_dump(mode="json") for r in results]
    run.write_json_atomic(
        "answering_evaluation_report.json",
        {
            "summary": summary.model_dump(mode="json"),
            "per_case": result_rows,
            "duration_s": round(time.perf_counter() - started, 3),
        },
    )
    run.write_text_atomic("answering_evaluation_summary.md", _render_summary_md(summary))
    logger.info("Answering evaluation complete: %s (%d case(s))", run.root.name, n)
    return run, results, summary


def _render_summary_md(summary: AnsweringEvaluationSummary) -> str:
    lines = [
        f"# Answering Evaluation Summary — {summary.run_id}",
        "",
        f"- Mode: `{summary.retrieval_mode}`",
        f"- Dataset: `{summary.dataset_path}` ({summary.case_count} case(s), hash `{summary.dataset_hash[:12]}`)",
        "",
        "## Metrics",
        "",
        f"- Structured-output validity rate: {summary.structured_output_validity_rate:.3f}",
        f"- Answer/refusal success rate: {summary.answer_or_refusal_success_rate:.3f}",
        f"- Refusal precision: {_fmt(summary.refusal_precision)}",
        f"- Refusal recall: {_fmt(summary.refusal_recall)}",
        f"- Citation validity rate: {summary.citation_validity_rate:.3f}",
        f"- Unknown-citation rate: {summary.unknown_citation_rate:.3f}",
        f"- Supporting-quote validity rate: {_fmt(summary.supporting_quote_validity_rate)}",
        f"- Mean citation coverage: {_fmt(summary.mean_citation_coverage)}",
        f"- Expected-source precision: {_fmt(summary.expected_source_precision)}",
        f"- Expected-source recall: {_fmt(summary.expected_source_recall)}",
        f"- Context-budget compliance: {summary.context_budget_compliance_rate:.3f}",
        f"- Artifact completeness: {summary.artifact_completeness_rate:.3f}",
        f"- Generation failure rate: {summary.generation_failure_rate:.3f}",
        f"- Grounding validation pass rate: {summary.grounding_pass_rate:.3f}",
        "",
        f"- Latency p50: {summary.latency_p50_s:.2f}s  |  p95: {summary.latency_p95_s:.2f}s",
        f"- Mean prompt tokens: {_fmt(summary.mean_prompt_token_count)}  |  "
        f"Mean answer tokens: {_fmt(summary.mean_answer_token_count)}",
        "",
        "## Limitations",
        "",
    ]
    lines += [f"- {item}" for item in summary.limitations]
    lines += ["", "## Reproduction", "", "```", summary.reproduction_command, "```"]
    return "\n".join(lines) + "\n"


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"

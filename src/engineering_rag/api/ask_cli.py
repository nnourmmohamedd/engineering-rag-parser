"""``engrag-ask`` command line interface.

Argument parsing and presentation only -- every bit of logic lives in
:mod:`engineering_rag.pipelines.answering_pipeline` and
:mod:`engineering_rag.pipelines.answering_evaluation`. Mirrors
``engrag-retrieve``'s structure and UX.

Never prints the system prompt, chain-of-thought, or a full source document
in normal output -- only ``--verbose`` prints the prompt manifest, and even
that never includes hidden reasoning (the model runs with ``think: false``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from engineering_rag.api.cli import _force_utf8_streams
from engineering_rag.clients.ollama import OllamaError
from engineering_rag.databases.bm25.errors import BM25Error
from engineering_rag.pipelines.answering_config import AnsweringPipelineConfig, load_answering_config
from engineering_rag.pipelines.answering_evaluation import run_answering_evaluation
from engineering_rag.pipelines.answering_pipeline import run_ask_pipeline, run_context_pipeline, validate_all
from engineering_rag.pipelines.retrieval_config import RetrievalConfig, load_retrieval_config
from engineering_rag.services.answerer import ANSWERER_VERSION
from engineering_rag.services.context_builder import ContextBuilderError
from engineering_rag.services.reranker import RerankerError
from engineering_rag.services.retriever import CorpusCompatibilityError, RetrievalError
from engineering_rag.utils.logging import configure_logging

_force_utf8_streams()

app = typer.Typer(
    name="engrag-ask",
    help="Grounded LLM answer generation over the existing retrieval system, via a local Ollama model.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console(stderr=True)
_stdout = Console()

_DEFAULT_RETRIEVAL_PROFILE = Path("configs/retrieval_production.yaml")
_RETRIEVAL_MODES = ("vector", "hybrid", "hybrid-rerank", "vector-rerank")

_ProfileOption = Annotated[
    Path,
    typer.Option("--profile", "-c", help="Answering YAML config profile file.", exists=True, dir_okay=False),
]
_RetrievalProfileOption = Annotated[
    Path,
    typer.Option(
        "--retrieval-profile", help="Retrieval YAML config profile file.", exists=True, dir_okay=False
    ),
]
_RetrievalModeOption = Annotated[
    str | None, typer.Option("--retrieval-mode", help=f"One of: {', '.join(_RETRIEVAL_MODES)}.")
]


def _load(
    profile: Path, retrieval_profile: Path, log_level: str
) -> tuple[AnsweringPipelineConfig, RetrievalConfig]:
    answering_config = load_answering_config(profile)
    retrieval_config = load_retrieval_config(retrieval_profile)
    if log_level != "INFO":
        answering_config = answering_config.model_copy(
            update={"logging": answering_config.logging.model_copy(update={"log_level": log_level})}
        )
    return answering_config, retrieval_config


def _resolve_mode(answering_config: AnsweringPipelineConfig, retrieval_mode: str | None) -> str:
    mode = retrieval_mode or answering_config.answering.default_retrieval_mode
    if mode not in _RETRIEVAL_MODES:
        console.print(f"[bold red]Invalid --retrieval-mode:[/] {mode!r}. Must be one of: {_RETRIEVAL_MODES}")
        raise typer.Exit(2)
    return mode


def _checks_table(title: str, checks: list[dict[str, object]]) -> Table:
    table = Table(title=title)
    table.add_column("check")
    table.add_column("status")
    table.add_column("summary")
    for check in checks:
        mark = "[green]OK[/]" if check["passed"] else "[red]FAIL[/]"
        table.add_row(str(check["check_id"]), mark, str(check["summary"]))
    return table


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", help="Show version and exit.")] = False,
) -> None:
    """Root callback: handles ``--version`` before a subcommand is required."""
    if version:
        _stdout.print(f"engrag-ask {ANSWERER_VERSION}")
        raise typer.Exit(0)
    if ctx.invoked_subcommand is None:
        _stdout.print(ctx.get_help())
        raise typer.Exit(0)


@app.command("validate")
def validate_cmd(
    profile: _ProfileOption,
    retrieval_profile: _RetrievalProfileOption = _DEFAULT_RETRIEVAL_PROFILE,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON on stdout.")] = False,
) -> None:
    """Check Ollama reachability/version/model/digest, the retrieval database, and config -- never generates."""
    answering_config, retrieval_config = _load(profile, retrieval_profile, "INFO")
    report = validate_all(answering_config, retrieval_config)

    if as_json:
        _stdout.print_json(json.dumps(report.as_dict()))
        raise typer.Exit(0 if report.passed else 1)

    style = "bold green" if report.passed else "bold red"
    _stdout.print(f"[{style}]{'PASS' if report.passed else 'FAIL'}[/]")
    _stdout.print(_checks_table("Ollama", report.ollama.checks))
    _stdout.print(_checks_table("Retrieval", report.retrieval.checks))
    _stdout.print(_checks_table("Config", report.config_checks))
    raise typer.Exit(0 if report.passed else 1)


@app.command("context")
def context_cmd(
    query: Annotated[str, typer.Option("--query", "-q", help="Free-text question.")],
    profile: _ProfileOption,
    retrieval_profile: _RetrievalProfileOption = _DEFAULT_RETRIEVAL_PROFILE,
    retrieval_mode: _RetrievalModeOption = None,
    top_k: Annotated[int | None, typer.Option("--top-k", help="Retrieval candidate count override.")] = None,
    no_neighbors: Annotated[bool, typer.Option("--no-neighbors", help="Disable neighbor expansion.")] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit the ContextPackage as JSON on stdout.")
    ] = False,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write the JSON context to a file.")
    ] = None,
    log_level: Annotated[str, typer.Option("--log-level", help="DEBUG|INFO|WARNING|ERROR")] = "INFO",
) -> None:
    """Run retrieval + context building only. NEVER calls the LLM."""
    configure_logging(console_level=log_level, quiet_console=as_json)
    answering_config, retrieval_config = _load(profile, retrieval_profile, log_level)
    mode = _resolve_mode(answering_config, retrieval_mode)

    try:
        _retrieval_response, context = run_context_pipeline(
            query,
            answering_config,
            retrieval_config,
            retrieval_mode=mode,
            top_k=top_k,
            neighbors_enabled=not no_neighbors,
        )
    except CorpusCompatibilityError as exc:
        console.print(f"[bold red]Corpus compatibility check failed:[/] {exc}")
        raise typer.Exit(5) from exc
    except (BM25Error, RerankerError, ContextBuilderError, RetrievalError) as exc:
        console.print(f"[bold red]Context build failed:[/] {type(exc).__name__}: {exc}")
        raise typer.Exit(3) from exc

    payload = context.model_dump(mode="json")
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")

    if as_json:
        _stdout.print_json(json.dumps(payload))
        raise typer.Exit(0)

    table = Table(
        title=f"context [{mode}]: {query!r} "
        f"({context.total_sources_selected}/{context.total_candidates_received} selected)"
    )
    table.add_column("citation", style="cyan")
    table.add_column("chunk_id")
    table.add_column("source")
    table.add_column("pages")
    table.add_column("neighbor")
    table.add_column("tokens", justify="right")
    table.add_column("snippet")
    for source in context.selected_sources:
        pages = ",".join(str(p) for p in source.page_numbers) or "-"
        snippet = source.retrieval_text[:60].replace("\n", " ")
        table.add_row(
            source.citation_id,
            source.chunk_id,
            source.source_filename or "-",
            pages,
            "yes" if source.is_neighbor else "no",
            str(source.token_count),
            snippet,
        )
    _stdout.print(table)
    _stdout.print(
        f"[dim]tokens: {context.context_token_count}/{context.token_budget}  "
        f"excluded: {len(context.excluded_candidates)}[/]"
    )
    for excluded in context.excluded_candidates:
        _stdout.print(f"[yellow]excluded[/] {excluded.chunk_id}: {excluded.reason} ({excluded.detail})")
    for warning in context.warnings:
        _stdout.print(f"[yellow]Warning:[/] {warning}")
    if output is not None:
        _stdout.print(f"[dim]Written to:[/] {output}")


@app.command("ask")
def ask_cmd(
    query: Annotated[str, typer.Option("--query", "-q", help="Free-text question.")],
    profile: _ProfileOption,
    retrieval_profile: _RetrievalProfileOption = _DEFAULT_RETRIEVAL_PROFILE,
    retrieval_mode: _RetrievalModeOption = None,
    top_k: Annotated[int | None, typer.Option("--top-k", help="Retrieval candidate count override.")] = None,
    no_neighbors: Annotated[bool, typer.Option("--no-neighbors", help="Disable neighbor expansion.")] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit the AnswerResponse as JSON on stdout.")
    ] = False,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write the JSON answer to a file.")
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Also print the grounding report and stage latencies.")
    ] = False,
    log_level: Annotated[str, typer.Option("--log-level", help="DEBUG|INFO|WARNING|ERROR")] = "INFO",
) -> None:
    """Ask a grounded question. Exits non-zero unless the final status is answered/insufficient_evidence."""
    configure_logging(console_level=log_level, quiet_console=as_json)
    answering_config, retrieval_config = _load(profile, retrieval_profile, log_level)
    mode = _resolve_mode(answering_config, retrieval_mode)

    try:
        _retrieval_response, _context, answer, _trace, run_dir = run_ask_pipeline(
            query,
            answering_config,
            retrieval_config,
            retrieval_mode=mode,
            top_k=top_k,
            neighbors_enabled=not no_neighbors,
        )
    except CorpusCompatibilityError as exc:
        console.print(f"[bold red]Corpus compatibility check failed:[/] {exc}")
        raise typer.Exit(5) from exc
    except (BM25Error, RerankerError, ContextBuilderError) as exc:
        console.print(f"[bold red]Context build failed:[/] {type(exc).__name__}: {exc}")
        raise typer.Exit(3) from exc
    except OllamaError as exc:
        console.print(f"[bold red]Ollama error:[/] {type(exc).__name__}: {exc}")
        raise typer.Exit(6) from exc
    except RetrievalError as exc:
        console.print(f"[bold red]Retrieval failed:[/] {exc}")
        raise typer.Exit(3) from exc

    payload = answer.model_dump(mode="json")
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")

    exit_code = 0 if answer.status in ("answered", "insufficient_evidence") else 1

    if as_json:
        _stdout.print_json(json.dumps(payload))
        raise typer.Exit(exit_code)

    status_style = {
        "answered": "bold green",
        "insufficient_evidence": "bold yellow",
        "generation_failed": "bold red",
        "validation_failed": "bold red",
    }.get(answer.status, "bold")
    _stdout.print(f"[{status_style}]{answer.status.upper()}[/]  mode={mode}")
    _stdout.print(answer.answer)

    if answer.citations:
        _stdout.print("")
        _stdout.print("[bold]Citations:[/]")
        for citation in answer.citations:
            pages = ",".join(str(p) for p in citation.page_numbers) or "-"
            section = f" — {citation.section_title}" if citation.section_title else ""
            _stdout.print(f"  [{citation.citation_id}] {citation.source_filename or '-'} p.{pages}{section}")

    _stdout.print(
        f"[dim]validation={answer.validation.status}  repair_attempted={answer.repair_attempted}  "
        f"model={answer.model_tag}  total_latency={answer.total_latency_s:.2f}s[/]"
    )
    if answer.warnings:
        for warning in answer.warnings:
            _stdout.print(f"[yellow]Warning:[/] {warning}")
    if verbose:
        _stdout.print(f"[dim]stage_latencies:[/] {answer.stage_latencies_s}")
        _stdout.print(f"[dim]grounding checks_failed:[/] {answer.validation.checks_failed}")
        _stdout.print(f"[dim]grounding checks_passed:[/] {answer.validation.checks_passed}")
    if run_dir is not None:
        _stdout.print(f"[dim]Artifacts:[/] {run_dir.root}")
    if output is not None:
        _stdout.print(f"[dim]Written to:[/] {output}")
    raise typer.Exit(exit_code)


@app.command("evaluate")
def evaluate_cmd(
    profile: _ProfileOption,
    retrieval_profile: _RetrievalProfileOption = _DEFAULT_RETRIEVAL_PROFILE,
    retrieval_mode: _RetrievalModeOption = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit the summary as JSON on stdout.")] = False,
    log_level: Annotated[str, typer.Option("--log-level", help="DEBUG|INFO|WARNING|ERROR")] = "INFO",
) -> None:
    """Run the answering ground-truth benchmark and write a full report under a new run directory."""
    configure_logging(console_level=log_level, quiet_console=as_json)
    answering_config, retrieval_config = _load(profile, retrieval_profile, log_level)
    mode = _resolve_mode(answering_config, retrieval_mode)

    try:
        run_dir, _results, summary = run_answering_evaluation(
            answering_config,
            retrieval_config,
            retrieval_mode=mode,
            reproduction_command=f"engrag-ask evaluate --profile {profile} --retrieval-mode {mode}",
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[bold red]Evaluation dataset rejected:[/] {exc}")
        raise typer.Exit(2) from exc

    if as_json:
        _stdout.print_json(summary.model_dump_json())
        return

    _stdout.print(f"[bold]Answering evaluation run:[/] {run_dir.root}  [dim]mode=[/]{summary.retrieval_mode}")
    _stdout.print(f"[dim]Cases:[/] {summary.case_count}")
    _stdout.print(f"  Structured-output validity: {summary.structured_output_validity_rate:.3f}")
    _stdout.print(f"  Answer/refusal success: {summary.answer_or_refusal_success_rate:.3f}")
    _stdout.print(f"  Grounding pass rate: {summary.grounding_pass_rate:.3f}")
    _stdout.print(f"  Citation validity rate: {summary.citation_validity_rate:.3f}")
    _stdout.print(f"[dim]Report:[/] {run_dir.root / 'answering_evaluation_summary.md'}")


def main() -> None:
    """Console-script entry point."""
    app()

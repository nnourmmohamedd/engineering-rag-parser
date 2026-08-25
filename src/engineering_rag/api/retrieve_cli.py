"""``engrag-retrieve`` command line interface.

Argument parsing and presentation only — every bit of logic lives in
:mod:`engineering_rag.pipelines.retrieval_pipeline` and the services/adapters
it composes. Mirrors ``engrag-index``'s structure and UX exactly.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from engineering_rag.api.cli import _force_utf8_streams
from engineering_rag.pipelines.retrieval_config import RetrievalConfig, load_retrieval_config
from engineering_rag.pipelines.retrieval_pipeline import (
    inspect_collection,
    run_evaluation_pipeline,
    run_search,
    validate_environment,
)
from engineering_rag.services.retriever import RETRIEVER_VERSION, InvalidFilterError, RetrievalError
from engineering_rag.utils.logging import configure_logging

_force_utf8_streams()

app = typer.Typer(
    name="engrag-retrieve",
    help="Embed a query with BGE, search the existing ChromaDB collection, and evaluate retrieval quality.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console(stderr=True)
_stdout = Console()


def _load(profile: Path | None, log_level: str) -> RetrievalConfig:
    config = load_retrieval_config(profile)
    if log_level != "INFO":
        config = config.model_copy(
            update={"logging": config.logging.model_copy(update={"log_level": log_level})}
        )
    return config


def _parse_filters(raw: list[str]) -> dict[str, str | int | float | bool]:
    filters: dict[str, str | int | float | bool] = {}
    for item in raw:
        if "=" not in item:
            raise typer.BadParameter(f"--filter must be KEY=VALUE, got: {item!r}")
        key, value = item.split("=", 1)
        filters[key.strip()] = value.strip()
    return filters


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", help="Show version and exit.")] = False,
) -> None:
    """Root callback: handles ``--version`` before a subcommand is required."""
    if version:
        _stdout.print(f"engrag-retrieve {RETRIEVER_VERSION}")
        raise typer.Exit(0)
    if ctx.invoked_subcommand is None:
        _stdout.print(ctx.get_help())
        raise typer.Exit(0)


@app.command("search")
def search_cmd(
    query: Annotated[str, typer.Option("--query", "-q", help="Free-text query.")],
    profile: Annotated[
        Path, typer.Option("--profile", "-c", help="YAML config profile file.", exists=True, dir_okay=False)
    ],
    top_k: Annotated[
        int | None, typer.Option("--top-k", help="Number of results (defaults to the profile's).")
    ] = (None),
    collection: Annotated[
        str | None, typer.Option("--collection", help="Collection name (defaults to the profile's).")
    ] = None,
    filter_: Annotated[
        list[str], typer.Option("--filter", help="KEY=VALUE metadata filter; repeatable, ANDed together.")
    ] = [],  # noqa: B006 - typer requires a literal default for multi-value options
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit the full response as JSON on stdout.")
    ] = False,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write the JSON response to a file.")
    ] = (None),
    log_level: Annotated[str, typer.Option("--log-level", help="DEBUG|INFO|WARNING|ERROR")] = "INFO",
) -> None:
    """Embed a query with BGE and search the existing collection. Exits non-zero on failure."""
    configure_logging(console_level=log_level, quiet_console=as_json)
    config = _load(profile, log_level)
    filters = _parse_filters(filter_)

    try:
        response = run_search(
            query, config, top_k=top_k, metadata_filters=filters, collection_name=collection
        )
    except InvalidFilterError as exc:
        console.print(f"[bold red]Invalid filter:[/] {exc}")
        raise typer.Exit(2) from exc
    except RetrievalError as exc:
        console.print(f"[bold red]Retrieval failed:[/] {exc}")
        raise typer.Exit(3) from exc
    except Exception as exc:  # noqa: BLE001 - surface a clean message, keep the trace in the log
        logging.getLogger(__name__).exception("Search failed")
        console.print(f"[bold red]Run failed:[/] {type(exc).__name__}: {exc}")
        raise typer.Exit(4) from exc

    payload = response.model_dump(mode="json")
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")

    if as_json:
        _stdout.print_json(json.dumps(payload))
        raise typer.Exit(0)

    table = Table(
        title=f"search: {query!r} in {response.collection_name!r} ({response.returned_count} hit(s))"
    )
    table.add_column("rank", justify="right")
    table.add_column("chunk_id", style="cyan")
    table.add_column("similarity")
    table.add_column("distance")
    table.add_column("source")
    table.add_column("pages")
    table.add_column("section")
    table.add_column("snippet")
    for hit in response.hits:
        sim = f"{hit.similarity_score:.4f}" if hit.similarity_score is not None else "n/a"
        pages = ",".join(str(p) for p in hit.page_numbers) or "-"
        snippet = hit.retrieval_text[:70].replace("\n", " ")
        table.add_row(
            str(hit.rank),
            hit.chunk_id,
            sim,
            f"{hit.raw_distance:.4f}",
            hit.source_filename or "-",
            pages,
            hit.section_title or "-",
            snippet,
        )
    _stdout.print(table)
    if response.warnings:
        for w in response.warnings:
            _stdout.print(f"[yellow]Warning:[/] {w}")
    _stdout.print(
        f"[dim]embedding={response.embedding_duration_s * 1000:.1f}ms  "
        f"db={response.database_duration_s * 1000:.1f}ms  total={response.total_duration_s * 1000:.1f}ms[/]"
    )
    if output is not None:
        _stdout.print(f"[dim]Written to:[/] {output}")


@app.command("inspect")
def inspect_cmd(
    profile: Annotated[
        Path, typer.Option("--profile", "-c", help="YAML config profile file.", exists=True, dir_okay=False)
    ],
    collection: Annotated[
        str | None, typer.Option("--collection", help="Collection name (defaults to the profile's).")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit statistics as JSON on stdout.")] = False,
) -> None:
    """Non-mutating inspection of the configured collection: path, count, metric, sample metadata keys."""
    config = load_retrieval_config(profile)
    report = inspect_collection(config, collection_name=collection)

    if as_json:
        _stdout.print_json(json.dumps(report.as_dict()))
        return

    if not report.exists:
        console.print(f"[bold red]No such collection:[/] {report.collection_name!r} at {report.chroma_path}")
        raise typer.Exit(2)

    table = Table(title=f"Collection — {report.collection_name}")
    table.add_column("Property", style="cyan")
    table.add_column("Value")
    table.add_row("Path", report.chroma_path)
    table.add_row("Count", str(report.count))
    table.add_row("Distance metric", report.distance_metric)
    table.add_row("Embedding dimension", str(report.embedding_dimension))
    table.add_row("Sample metadata keys", ", ".join(report.sample_metadata_keys))
    for filename, count in sorted(report.source_filename_distribution.items()):
        table.add_row(f"  source: {filename}", str(count))
    _stdout.print(table)


@app.command("validate")
def validate_cmd(
    profile: Annotated[
        Path, typer.Option("--profile", "-c", help="YAML config profile file.", exists=True, dir_okay=False)
    ],
    collection: Annotated[
        str | None, typer.Option("--collection", help="Collection name (defaults to the profile's).")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON on stdout.")] = False,
) -> None:
    """Run non-destructive database and compatibility checks. Exits non-zero on any failed check."""
    config = load_retrieval_config(profile)
    report = validate_environment(config, collection_name=collection)

    if as_json:
        _stdout.print_json(json.dumps(report.as_dict()))
        raise typer.Exit(0 if report.passed else 1)

    style = "bold green" if report.passed else "bold red"
    _stdout.print(f"[{style}]{'PASS' if report.passed else 'FAIL'}[/]")
    for check in report.checks:
        mark = "[green]OK[/]" if check["passed"] else "[red]FAIL[/]"
        _stdout.print(f"  {mark}  {check['check_id']}: {check['summary']}")
    raise typer.Exit(0 if report.passed else 1)


@app.command("evaluate")
def evaluate_cmd(
    profile: Annotated[
        Path, typer.Option("--profile", "-c", help="YAML config profile file.", exists=True, dir_okay=False)
    ],
    collection: Annotated[
        str | None, typer.Option("--collection", help="Collection name (defaults to the profile's).")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit the summary as JSON on stdout.")] = False,
    log_level: Annotated[str, typer.Option("--log-level", help="DEBUG|INFO|WARNING|ERROR")] = "INFO",
) -> None:
    """Run the ground-truth retrieval benchmark and write a full report under a new run directory."""
    configure_logging(console_level=log_level, quiet_console=as_json)
    config = _load(profile, log_level)

    try:
        run_dir, _rows, summary = run_evaluation_pipeline(
            config,
            collection_name=collection,
            reproduction_command=f"engrag-retrieve evaluate --profile {profile}",
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[bold red]Evaluation dataset rejected:[/] {exc}")
        raise typer.Exit(2) from exc
    except RetrievalError as exc:
        console.print(f"[bold red]Evaluation failed:[/] {exc}")
        raise typer.Exit(3) from exc

    if as_json:
        _stdout.print_json(summary.model_dump_json())
        return

    _stdout.print(f"[bold]Evaluation run:[/] {run_dir.root}")
    _stdout.print(
        f"[dim]Cases:[/] {summary.case_count}  [dim]Human-reviewed:[/] {summary.human_reviewed_count}"
    )
    for k in summary.k_values:
        _stdout.print(
            f"  K={k}  HitRate={summary.hit_rate_at_k.get(k, 0.0):.3f}  "
            f"Recall={summary.recall_at_k.get(k, 0.0):.3f}  "
            f"Precision={summary.precision_at_k.get(k, 0.0):.3f}  nDCG={summary.ndcg_at_k.get(k, 0.0):.3f}"
        )
    _stdout.print(f"[dim]MRR:[/] {summary.mean_reciprocal_rank:.3f}")
    _stdout.print(f"[dim]Report:[/] {run_dir.root / 'retrieval_evaluation_summary.md'}")


def main() -> None:
    """Console-script entry point."""
    app()

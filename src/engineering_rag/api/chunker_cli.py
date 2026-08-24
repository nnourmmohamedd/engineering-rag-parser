"""``engrag-chunk`` command line interface.

A separate console script from ``engrag-parse``, matching the mentor's
desired UX (``engrag-chunk run/inspect/validate``) and this project's
convention of a dedicated Typer app per capability rather than nesting
unrelated capabilities under one root command — the two share no options and
would otherwise force one root ``--version``/``--help`` to describe two
unrelated tools. Both live under ``api/`` (the application boundary) and
both are wired the same way: this module is the *only* place chunker
logging is configured and the only place that calls into
:mod:`engineering_rag.pipelines.chunking_pipeline`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from engineering_rag.api.cli import _force_utf8_streams
from engineering_rag.pipelines.chunking_pipeline import run_chunking_pipeline
from engineering_rag.services.chunker import CHUNKER_VERSION, ChunkerConfig, ChunkerInputError, load_config
from engineering_rag.services.chunker.models import ChunkValidationReport, RunStatus
from engineering_rag.utils.logging import configure_logging
from engineering_rag.utils.paths import default_chunker_output_root

_force_utf8_streams()

app = typer.Typer(
    name="engrag-chunk",
    help="Hierarchical-first, tokenizer-aware chunking of parser-produced document.json.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console(stderr=True)
_stdout = Console()

_STATUS_STYLE = {"PASS": "bold green", "PASS_WITH_WARNINGS": "bold yellow", "FAIL": "bold red"}


def _load(config_path: Path | None, strict: bool, log_level: str) -> ChunkerConfig:
    overrides: dict[str, Any] = {"strict": strict, "log_level": log_level}
    return load_config(config_path, **overrides)


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", help="Show version and exit.")] = False,
) -> None:
    """Root callback: handles ``--version`` before a subcommand is required."""
    if version:
        _stdout.print(f"engrag-chunk {CHUNKER_VERSION}")
        raise typer.Exit(0)
    if ctx.invoked_subcommand is None:
        _stdout.print(ctx.get_help())
        raise typer.Exit(0)


@app.command("run")
def run_cmd(
    input_path: Annotated[
        Path,
        typer.Option(
            "--input",
            "-i",
            help="A document.json file, or a parser run directory containing docling/document.json.",
            exists=True,
        ),
    ],
    profile: Annotated[
        Path | None,
        typer.Option("--profile", "-c", help="YAML config profile file.", exists=True, dir_okay=False),
    ] = None,
    output: Annotated[Path | None, typer.Option("--output", help="Base directory for run artifacts.")] = None,
    strict: Annotated[bool, typer.Option("--strict", help="Treat warnings as failures.")] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit a machine-readable summary on stdout.")
    ] = False,
    log_level: Annotated[str, typer.Option("--log-level", help="DEBUG|INFO|WARNING|ERROR")] = "INFO",
    log_file: Annotated[Path | None, typer.Option("--log-file")] = None,
) -> None:
    """Chunk a parser document.json end to end. Exits non-zero on FAIL."""
    configure_logging(console_level=log_level, quiet_console=as_json, log_file=log_file)
    config = _load(profile, strict, log_level)
    output_root = output if output is not None else default_chunker_output_root()
    try:
        result = run_chunking_pipeline(input_path, config, output_root)
    except ChunkerInputError as exc:
        console.print(f"[bold red]Input rejected:[/] {exc}")
        raise typer.Exit(2) from exc
    except Exception as exc:  # noqa: BLE001 - surface a clean message, keep the trace in the log
        logging.getLogger(__name__).exception("Run failed")
        console.print(f"[bold red]Run failed:[/] {type(exc).__name__}: {exc}")
        raise typer.Exit(3) from exc

    if as_json:
        _stdout.print_json(
            json.dumps(
                {
                    "status": result.status,
                    "run_dir": result.run_dir.as_posix(),
                    "exit_code": result.exit_code,
                    "chunk_count": result.chunk_count,
                    "timings_s": {k: round(v, 2) for k, v in result.timings.items()},
                }
            )
        )
    else:
        style = _STATUS_STYLE.get(result.status, "bold")
        _stdout.print()
        _stdout.print(f"[{style}]{result.status}[/]  ->  {result.run_dir}")
        _stdout.print(f"[dim]{result.chunk_count} chunk(s) written to chunks.jsonl[/]")
        _stdout.print(f"[dim]Summary: {result.run_dir / 'chunking_summary.md'}[/]")
    raise typer.Exit(result.exit_code)


@app.command("inspect")
def inspect_cmd(
    input_path: Annotated[
        Path, typer.Option("--input", "-i", help="Path to a chunks.jsonl file.", exists=True, dir_okay=False)
    ],
    as_json: Annotated[bool, typer.Option("--json", help="Emit statistics as JSON on stdout.")] = False,
) -> None:
    """Summarise an existing chunks.jsonl: counts, content types, token stats."""
    lines = [line for line in input_path.read_text(encoding="utf-8").split("\n") if line.strip()]
    records = [json.loads(line) for line in lines]
    counts: dict[str, int] = {}
    tokens = []
    for r in records:
        counts[r["content_type"]] = counts.get(r["content_type"], 0) + 1
        tokens.append(r["token_count"])

    stats = {
        "chunk_count": len(records),
        "content_type_counts": counts,
        "min_tokens": min(tokens) if tokens else 0,
        "max_tokens": max(tokens) if tokens else 0,
        "mean_tokens": round(sum(tokens) / len(tokens), 1) if tokens else 0,
    }
    if as_json:
        _stdout.print_json(json.dumps(stats))
        return

    table = Table(title=f"Chunks — {input_path}")
    table.add_column("Property", style="cyan")
    table.add_column("Value")
    table.add_row("Total chunks", str(stats["chunk_count"]))
    for content_type, count in sorted(counts.items()):
        table.add_row(f"  {content_type}", str(count))
    table.add_row(
        "Token count (min/mean/max)",
        f"{stats['min_tokens']} / {stats['mean_tokens']} / {stats['max_tokens']}",
    )
    _stdout.print(table)


@app.command("validate")
def validate_cmd(
    input_path: Annotated[
        Path, typer.Option("--input", help="Existing chunker run directory.", exists=True, file_okay=False)
    ],
    strict: Annotated[bool, typer.Option("--strict", help="Treat warnings as failures.")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON on stdout.")] = False,
) -> None:
    """Re-evaluate a stored validation report, optionally under strict rules."""
    report_path = input_path / "validation_report.json"
    if not report_path.is_file():
        console.print(f"[bold red]No validation report at[/] {report_path}")
        raise typer.Exit(2)
    report = ChunkValidationReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    status = report.compute_status(strict)

    if as_json:
        _stdout.print_json(
            json.dumps(
                {
                    "status": status.value,
                    "strict": strict,
                    "run_dir": input_path.as_posix(),
                    "failed_gates": [c.check_id for c in report.failed_gates],
                    "warnings": [c.check_id for c in report.warnings],
                }
            )
        )
    else:
        style = _STATUS_STYLE.get(status.value, "bold")
        _stdout.print(f"[{style}]{status.value}[/]  ->  {input_path}")
        if report.failed_gates:
            _stdout.print(
                f"[red]{len(report.failed_gates)} failed gate(s):[/] {[c.check_id for c in report.failed_gates]}"
            )
        if strict and report.warnings:
            console.print(f"[yellow]Strict mode: {len(report.warnings)} warning(s) escalated to failure.[/]")
    raise typer.Exit(1 if status is RunStatus.FAIL else 0)


def main() -> None:
    """Console-script entry point."""
    app()

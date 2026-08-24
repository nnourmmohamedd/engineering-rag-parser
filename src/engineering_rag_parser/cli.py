"""``engrag-parse`` command line interface.

Subcommands mirror the pipeline stages so each can be exercised in isolation:
``inspect`` (preflight only), ``run`` (end to end), ``validate`` (re-check an
existing run) and ``show`` (summarise a run). Every command supports ``--json``
for automation, and ``run``/``validate`` exit non-zero on ``FAIL``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from . import __version__
from .config import ParserConfig, Profile, load_config
from .domain import RunStatus, Severity, ValidationReport
from .pipeline import run_pipeline
from .preflight import PreflightError, inspect_source


def _force_utf8_streams() -> None:
    """Reconfigure stdout/stderr to UTF-8 so console output never crashes the CLI.

    A Windows console running a legacy non-UTF-8 codepage (e.g. cp1256) cannot
    encode characters Rich writes by default (an arrow in the status line, a
    warning icon) and raises an unhandled `UnicodeEncodeError` straight out of
    the terminal renderer — turning a routine `validate --strict` into a stack
    trace instead of the intended exit code. `errors="replace"` degrades a
    handful of glyphs to `?` rather than crashing the process.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):  # stream not reconfigurable
                reconfigure(encoding="utf-8", errors="replace")


_force_utf8_streams()

app = typer.Typer(
    name="engrag-parse",
    help="Engineering-grade, local-first PDF parsing built on Docling.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console(stderr=True)
_stdout = Console()

_STATUS_STYLE = {
    RunStatus.PASS: "bold green",
    RunStatus.PASS_WITH_WARNINGS: "bold yellow",
    RunStatus.FAIL: "bold red",
}


def _setup_logging(level: str, quiet: bool) -> None:
    """Route logs to stderr so ``--json`` on stdout stays machine-parseable."""
    logging.basicConfig(
        level="ERROR" if quiet else level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
        force=True,
    )


def _load(config_path: Path | None, profile: str | None, strict: bool, log_level: str) -> ParserConfig:
    """Build the effective configuration from file plus CLI overrides."""
    overrides: dict[str, Any] = {"strict": strict, "log_level": log_level}
    if profile:
        overrides["profile"] = Profile(profile)
    return load_config(config_path, **overrides)


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", help="Show version and exit.")] = False,
) -> None:
    """Root callback: handles ``--version`` before a subcommand is required."""
    if version:
        _stdout.print(f"engrag-parse {__version__}")
        raise typer.Exit(0)
    if ctx.invoked_subcommand is None:
        _stdout.print(ctx.get_help())
        raise typer.Exit(0)


@app.command("inspect")
def inspect_cmd(
    input_path: Annotated[
        Path,
        typer.Option("--input", "-i", help="PDF to inspect.", exists=True, dir_okay=False, readable=True),
    ],
    config_path: Annotated[
        Path | None, typer.Option("--config", "-c", help="YAML config file.", exists=True, dir_okay=False)
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit the manifest as JSON on stdout.")] = False,
    log_level: Annotated[str, typer.Option("--log-level")] = "INFO",
) -> None:
    """Run preflight only: an independent source inventory, without Docling."""
    _setup_logging(log_level, quiet=as_json)
    config = _load(config_path, None, False, log_level)
    try:
        manifest = inspect_source(input_path, config)
    except PreflightError as exc:
        console.print(f"[bold red]Preflight rejected the input:[/] {exc}")
        raise typer.Exit(2) from exc

    if as_json:
        _stdout.print_json(json.dumps(manifest.model_dump(mode="json"), default=str))
        return

    table = Table(title=f"Preflight — {manifest.filename}", show_lines=False)
    table.add_column("Property", style="cyan")
    table.add_column("Value")
    rows = [
        ("SHA-256", manifest.sha256),
        ("Bytes", f"{manifest.byte_size:,}"),
        ("PDF version", manifest.pdf_version or "unknown"),
        ("Encrypted", str(manifest.is_encrypted)),
        ("Pages", str(manifest.page_count)),
        ("Characters", f"{manifest.total_char_count:,}"),
        ("Words", f"{manifest.total_word_count:,}"),
        ("Images (total)", str(manifest.total_image_count)),
        ("Images (substantive)", str(manifest.substantive_image_count)),
        ("Images (decorative repeats)", str(manifest.decorative_image_count)),
        ("Outline entries", str(len(manifest.outline_entries))),
        ("Fonts", ", ".join(manifest.fonts[:4]) or "—"),
        ("Sparse pages", str(manifest.sparse_pages) or "—"),
        ("Image-heavy pages", str(manifest.image_heavy_pages) or "—"),
        ("Pages needing visual review", str(manifest.visual_review_pages)),
    ]
    for key, value in rows:
        table.add_row(key, value)
    _stdout.print(table)

    if manifest.furniture_candidates:
        furn = Table(title="Repeated furniture candidates")
        furn.add_column("Kind", style="magenta")
        furn.add_column("Band")
        furn.add_column("Pages", justify="right")
        furn.add_column("Text")
        for cand in manifest.furniture_candidates[:10]:
            furn.add_row(cand.kind, cand.band, f"{cand.page_fraction:.0%}", cand.text[:60])
        _stdout.print(furn)


@app.command("run")
def run_cmd(
    input_path: Annotated[
        Path, typer.Option("--input", "-i", help="PDF to parse.", exists=True, dir_okay=False, readable=True)
    ],
    config_path: Annotated[
        Path | None, typer.Option("--config", "-c", help="YAML config file.", exists=True, dir_okay=False)
    ] = None,
    artifacts: Annotated[Path, typer.Option("--artifacts", help="Base directory for run artifacts.")] = Path(
        "artifacts"
    ),
    profile: Annotated[str | None, typer.Option("--profile", help="Override the config profile.")] = None,
    strict: Annotated[bool, typer.Option("--strict", help="Treat warnings as failures.")] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit a machine-readable summary on stdout.")
    ] = False,
    log_level: Annotated[str, typer.Option("--log-level")] = "INFO",
) -> None:
    """Parse, export and validate a PDF end to end. Exits non-zero on FAIL."""
    _setup_logging(log_level, quiet=as_json)
    config = _load(config_path, profile, strict, log_level)
    try:
        result = run_pipeline(input_path, config, artifacts)
    except PreflightError as exc:
        console.print(f"[bold red]Preflight rejected the input:[/] {exc}")
        raise typer.Exit(2) from exc
    except Exception as exc:  # noqa: BLE001 - surface a clean message, keep the trace in the log
        logging.getLogger(__name__).exception("Run failed")
        console.print(f"[bold red]Run failed:[/] {type(exc).__name__}: {exc}")
        raise typer.Exit(3) from exc

    if as_json:
        _stdout.print_json(
            json.dumps(
                {
                    "status": result.status.value,
                    "run_dir": result.run_dir.as_posix(),
                    "exit_code": result.exit_code,
                    "failed_gates": [c.check_id for c in result.report.failed_gates],
                    "warnings": [c.check_id for c in result.report.warnings],
                    "human_review_items": result.report.human_review_items,
                    "timings_s": {k: round(v, 2) for k, v in result.timings.items()},
                }
            )
        )
    else:
        _print_summary(result.report, result.run_dir, result.timings)
    raise typer.Exit(result.exit_code)


@app.command("validate")
def validate_cmd(
    run_dir: Annotated[
        Path, typer.Option("--run", help="Existing run artifact directory.", exists=True, file_okay=False)
    ],
    strict: Annotated[bool, typer.Option("--strict", help="Treat warnings as failures.")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON on stdout.")] = False,
) -> None:
    """Re-evaluate a stored validation report, optionally under strict rules."""
    report_path = run_dir / "validation" / "report.json"
    if not report_path.is_file():
        console.print(f"[bold red]No validation report at[/] {report_path}")
        raise typer.Exit(2)
    report = ValidationReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    status = report.compute_status(strict)

    if as_json:
        _stdout.print_json(
            json.dumps(
                {
                    "status": status.value,
                    "strict": strict,
                    "run_dir": run_dir.as_posix(),
                    "failed_gates": [c.check_id for c in report.failed_gates],
                    "warnings": [c.check_id for c in report.warnings],
                }
            )
        )
    else:
        _print_summary(report, run_dir, {})
        if strict and report.warnings:
            console.print(f"[yellow]Strict mode: {len(report.warnings)} warning(s) escalated to failure.[/]")
    raise typer.Exit(1 if status is RunStatus.FAIL else 0)


@app.command("show")
def show_cmd(
    run_dir: Annotated[
        Path, typer.Option("--run", help="Run artifact directory.", exists=True, file_okay=False)
    ],
) -> None:
    """Print the artifact tree and headline metrics for a run."""
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.is_file():
        console.print(f"[bold red]No run manifest at[/] {manifest_path}")
        raise typer.Exit(2)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    table = Table(title=f"Run {manifest['run_id']}")
    table.add_column("Property", style="cyan")
    table.add_column("Value")
    table.add_row("Status", manifest["status"])
    table.add_row("Parser version", manifest["parser_version"])
    table.add_row("Profile", f"{manifest['profile']} — {manifest['profile_reason'][:80]}")
    table.add_row("Source", f"{manifest['source']['filename']} ({manifest['source']['page_count']} pages)")
    table.add_row("Source SHA-256", manifest["source"]["sha256"])
    table.add_row("Config hash", manifest["config_hash"][:16] + "…")
    table.add_row("Docling", manifest["docling"]["versions"].get("docling", "?"))
    table.add_row("Timings (s)", json.dumps(manifest["timings_s"]))
    table.add_row("Artifacts", f"{len(manifest['artifacts'])} files")
    _stdout.print(table)

    for warning in manifest.get("warnings", []):
        _stdout.print(f"[yellow]warning:[/] {warning}")


def _print_summary(report: ValidationReport, run_dir: Path, timings: dict[str, float]) -> None:
    """Render the terminal summary for a completed run."""
    style = _STATUS_STYLE[report.status]
    _stdout.print()
    _stdout.print(f"[{style}]{report.status.value}[/]  →  {run_dir}")
    _stdout.print()

    table = Table(title="Validation checks", show_lines=False)
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Gate", justify="center")
    table.add_column("Result", justify="center")
    table.add_column("Summary", overflow="fold")
    for check in report.checks:
        if check.passed:
            result = "[green]PASS[/]"
        elif check.severity is Severity.CRITICAL:
            result = "[red]FAIL[/]"
        else:
            result = "[yellow]WARN[/]"
        table.add_row(check.check_id, "●" if check.gate else "", result, check.summary[:110])
    _stdout.print(table)

    if report.human_review_items:
        _stdout.print()
        _stdout.print("[bold]Human review required:[/]")
        for item in report.human_review_items:
            _stdout.print(f"  • {item}")

    if timings:
        _stdout.print()
        _stdout.print("[dim]Timings (s): " + ", ".join(f"{k}={v:.1f}" for k, v in timings.items()) + "[/]")

    _stdout.print()
    _stdout.print(f"[dim]Report: {run_dir / 'validation' / 'report.md'}[/]")
    _stdout.print(f"[dim]Markdown: {run_dir / 'markdown' / 'document.md'}[/]")


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    sys.exit(app())

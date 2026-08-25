"""``engrag-index`` command line interface.

Argument parsing and presentation only — every bit of logic lives in
:mod:`engineering_rag.pipelines.indexing_pipeline` and the services/adapters
it composes. Mirrors ``engrag-chunk``'s structure and UX exactly.
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
from engineering_rag.databases.chroma import get_client
from engineering_rag.pipelines.indexing_config import IndexingConfig, load_indexing_config
from engineering_rag.pipelines.indexing_models import IndexRunStatus, IndexValidationReport
from engineering_rag.pipelines.indexing_pipeline import IndexingInputError, run_indexing_pipeline
from engineering_rag.services.embedder import EMBEDDER_VERSION
from engineering_rag.utils.logging import configure_logging

_force_utf8_streams()

app = typer.Typer(
    name="engrag-index",
    help="Embed BGE-aligned chunker output and store it in a persistent ChromaDB collection.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console(stderr=True)
_stdout = Console()

_STATUS_STYLE = {"PASS": "bold green", "PASS_WITH_WARNINGS": "bold yellow", "FAIL": "bold red"}


def _load(profile: Path | None, strict: bool, log_level: str) -> IndexingConfig:
    overrides: dict[str, object] = {}
    if strict:
        overrides["strict"] = True
    config = load_indexing_config(profile)
    if overrides:
        config = config.model_copy(update=overrides)
    if log_level != "INFO":
        config = config.model_copy(
            update={"logging": config.logging.model_copy(update={"log_level": log_level})}
        )
    return config


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", help="Show version and exit.")] = False,
) -> None:
    """Root callback: handles ``--version`` before a subcommand is required."""
    if version:
        _stdout.print(f"engrag-index {EMBEDDER_VERSION}")
        raise typer.Exit(0)
    if ctx.invoked_subcommand is None:
        _stdout.print(ctx.get_help())
        raise typer.Exit(0)


@app.command("build")
def build_cmd(
    input_path: Annotated[
        Path,
        typer.Option(
            "--input",
            "-i",
            help="A chunker run directory, or a chunks.jsonl file inside one.",
            exists=True,
        ),
    ],
    profile: Annotated[
        Path | None,
        typer.Option("--profile", "-c", help="YAML config profile file.", exists=True, dir_okay=False),
    ] = None,
    rebuild: Annotated[
        bool, typer.Option("--rebuild", help="Destructively delete and recreate the target collection first.")
    ] = False,
    strict: Annotated[bool, typer.Option("--strict", help="Treat warnings as failures.")] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit a machine-readable summary on stdout.")
    ] = False,
    log_level: Annotated[str, typer.Option("--log-level", help="DEBUG|INFO|WARNING|ERROR")] = "INFO",
    log_file: Annotated[Path | None, typer.Option("--log-file")] = None,
) -> None:
    """Embed a chunker run and store it in Chroma end to end. Exits non-zero on FAIL."""
    configure_logging(console_level=log_level, quiet_console=as_json, log_file=log_file)
    config = _load(profile, strict, log_level)

    if rebuild:
        _stdout.print(
            f"[bold yellow]--rebuild:[/] about to destructively replace collection "
            f"[bold]{config.chroma.collection_name}[/] at {config.chroma.persistence_path}"
        )

    try:
        result = run_indexing_pipeline(input_path, config, rebuild=rebuild)
    except IndexingInputError as exc:
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
                    "collection_name": result.collection_name,
                    "chroma_path": result.chroma_path,
                    "timings_s": {k: round(v, 2) for k, v in result.timings.items()},
                }
            )
        )
    else:
        style = _STATUS_STYLE.get(result.status, "bold")
        _stdout.print()
        _stdout.print(f"[{style}]{result.status}[/]  ->  {result.run_dir}")
        _stdout.print(f"[dim]Collection:[/] {result.collection_name}  [dim]Path:[/] {result.chroma_path}")
        _stdout.print(f"[dim]{result.chunk_count} chunk(s) processed.[/]")
        _stdout.print(f"[dim]Report:[/] {result.run_dir / 'index_summary.md'}")
    raise typer.Exit(result.exit_code)


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
    """Open a Chroma collection and print its count and stored identity metadata."""
    config = load_indexing_config(profile)
    name = collection or config.chroma.collection_name
    client = get_client(config.chroma.persistence_path, telemetry=config.chroma.telemetry)
    names = {c.name for c in client.list_collections()}
    if name not in names:
        console.print(f"[bold red]No such collection:[/] {name!r} at {config.chroma.persistence_path}")
        raise typer.Exit(2)
    coll = client.get_collection(name=name)
    stats = {
        "collection_name": name,
        "chroma_path": str(config.chroma.persistence_path),
        "count": coll.count(),
        "metadata": dict(coll.metadata or {}),
    }
    if as_json:
        _stdout.print_json(json.dumps(stats))
        return
    table = Table(title=f"Collection — {name}")
    table.add_column("Property", style="cyan")
    table.add_column("Value")
    table.add_row("Path", stats["chroma_path"])
    table.add_row("Count", str(stats["count"]))
    for k, v in sorted(stats["metadata"].items()):
        table.add_row(f"  {k}", str(v))
    _stdout.print(table)


@app.command("validate")
def validate_cmd(
    run: Annotated[
        Path,
        typer.Option("--run", help="Existing indexing run report directory.", exists=True, file_okay=False),
    ],
    strict: Annotated[bool, typer.Option("--strict", help="Treat warnings as failures.")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON on stdout.")] = False,
) -> None:
    """Re-evaluate a stored index_validation_report.json, optionally under strict rules."""
    report_path = run / "index_validation_report.json"
    if not report_path.is_file():
        console.print(f"[bold red]No validation report at[/] {report_path}")
        raise typer.Exit(2)
    report = IndexValidationReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    status = report.compute_status(strict)

    if as_json:
        _stdout.print_json(
            json.dumps(
                {
                    "status": status.value,
                    "strict": strict,
                    "run_dir": run.as_posix(),
                    "failed_gates": [c.check_id for c in report.failed_gates],
                    "warnings": [c.check_id for c in report.warnings],
                }
            )
        )
    else:
        style = _STATUS_STYLE.get(status.value, "bold")
        _stdout.print(f"[{style}]{status.value}[/]  ->  {run}")
        if report.failed_gates:
            _stdout.print(
                f"[red]{len(report.failed_gates)} failed gate(s):[/] {[c.check_id for c in report.failed_gates]}"
            )
        if strict and report.warnings:
            console.print(f"[yellow]Strict mode: {len(report.warnings)} warning(s) escalated to failure.[/]")
    raise typer.Exit(1 if status is IndexRunStatus.FAIL else 0)


@app.command("list")
def list_cmd(
    profile: Annotated[
        Path, typer.Option("--profile", "-c", help="YAML config profile file.", exists=True, dir_okay=False)
    ],
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON on stdout.")] = False,
) -> None:
    """List collections present at the configured Chroma persistence path."""
    config = load_indexing_config(profile)
    client = get_client(config.chroma.persistence_path, telemetry=config.chroma.telemetry)
    collections = client.list_collections()
    rows = [{"name": c.name, "count": c.count()} for c in collections]
    if as_json:
        _stdout.print_json(json.dumps(rows))
        return
    table = Table(title=f"Collections — {config.chroma.persistence_path}")
    table.add_column("Name", style="cyan")
    table.add_column("Count")
    for row in rows:
        table.add_row(row["name"], str(row["count"]))
    _stdout.print(table)


@app.command("smoke-query")
def smoke_query_cmd(
    query: Annotated[str, typer.Option("--query", "-q", help="Free-text query.")],
    profile: Annotated[
        Path, typer.Option("--profile", "-c", help="YAML config profile file.", exists=True, dir_okay=False)
    ],
    collection: Annotated[
        str | None, typer.Option("--collection", help="Collection name (defaults to the profile's).")
    ] = None,
    top_k: Annotated[int, typer.Option("--top-k", help="Number of results to return.")] = 5,
) -> None:
    """DIAGNOSTIC ONLY: embed a query and run a raw Chroma similarity search.

    This is not the final retrieval interface — no reranking, no BM25, no
    filtering. It exists solely to sanity-check that a build actually stores
    retrievable content.
    """
    from engineering_rag.services.embedder.bge import BGEEmbeddingService

    config = load_indexing_config(profile)
    name = collection or config.chroma.collection_name
    _stdout.print("[bold yellow]DIAGNOSTIC smoke-query — not the final retrieval interface.[/]")

    embedder = BGEEmbeddingService(config.embedding)
    vector = embedder.embed_query(query)

    client = get_client(config.chroma.persistence_path, telemetry=config.chroma.telemetry)
    coll = client.get_collection(name=name)
    result = coll.query(
        query_embeddings=[vector], n_results=top_k, include=["documents", "metadatas", "distances"]
    )

    table = Table(title=f"smoke-query: {query!r} in {name!r}")
    table.add_column("chunk_id", style="cyan")
    table.add_column("distance")
    table.add_column("heading")
    table.add_column("snippet")
    ids = result["ids"][0] if result["ids"] else []
    distances = result["distances"][0] if result.get("distances") else [None] * len(ids)
    documents = result["documents"][0] if result.get("documents") else [""] * len(ids)
    metadatas = result["metadatas"][0] if result.get("metadatas") else [{}] * len(ids)
    for cid, dist, doc, meta in zip(ids, distances, documents, metadatas, strict=True):
        heading = str((meta or {}).get("section_title") or "")
        snippet = (doc or "")[:80].replace("\n", " ")
        table.add_row(cid, f"{dist:.4f}" if dist is not None else "?", heading, snippet)
    _stdout.print(table)


def main() -> None:
    """Console-script entry point."""
    app()

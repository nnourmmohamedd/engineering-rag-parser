"""Load and validate the parser-produced ``document.json``.

The canonical chunking input is the DoclingDocument JSON the parser service
wrote — never the flattened Markdown, which drops per-item bounding boxes and
cannot reliably distinguish an unrecovered table from body text (see
``docs/productionization_options.md#future-ingestion-contract``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docling_core.types.doc import DoclingDocument

from engineering_rag.utils.hashing import sha256_file

__all__ = [
    "ChunkerInputError",
    "SourceIdentity",
    "load_document",
    "resolve_document_json_path",
]

logger = logging.getLogger(__name__)


class ChunkerInputError(RuntimeError):
    """Raised when the input cannot be loaded as a valid DoclingDocument."""


@dataclass
class SourceIdentity:
    """The parser's own identity for the document being chunked, carried forward."""

    document_json_path: Path
    document_json_sha256: str
    source_filename: str
    source_sha256: str
    run_manifest: dict[str, Any] = field(default_factory=dict)
    validation_report: dict[str, Any] = field(default_factory=dict)


def resolve_document_json_path(input_path: Path) -> Path:
    """Accept either a ``document.json`` file or a parser run directory.

    Raises:
        ChunkerInputError: if neither form resolves to an existing file.
    """
    input_path = Path(input_path)
    if input_path.is_file():
        return input_path
    if input_path.is_dir():
        candidate = input_path / "docling" / "document.json"
        if candidate.is_file():
            return candidate
        raise ChunkerInputError(
            f"{input_path} is a directory but does not contain docling/document.json "
            "(expected a parser run directory, e.g. data/output/parser/<doc>/<run-id>/)."
        )
    raise ChunkerInputError(f"Input not found: {input_path}")


def _load_sibling_json(path: Path, label: str) -> dict[str, Any]:
    """Best-effort load of a sibling parser artifact.

    Absent when ``document_json_path`` was supplied standalone rather than via
    a full parser run directory; the chunker still proceeds using facts
    derivable from the DoclingDocument itself.
    """
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read sibling %s at %s: %s", label, path, exc)
        return {}


def load_document(input_path: Path | str) -> tuple[DoclingDocument, SourceIdentity]:
    """Load, parse and reload-validate a parser-produced ``document.json``.

    Validation mirrors the parser's own round-trip gate: the file must parse
    as JSON *and* reload into the currently-installed ``DoclingDocument``
    model, so a schema drift between the Docling version that produced it and
    the one installed here is caught explicitly rather than failing deep
    inside the chunking logic.

    Raises:
        ChunkerInputError: with an actionable message, for any malformed or
            incompatible input.
    """
    document_json_path = resolve_document_json_path(Path(input_path))

    if not document_json_path.is_file():
        raise ChunkerInputError(f"document.json not found: {document_json_path}")

    raw_bytes = document_json_path.read_bytes()
    try:
        raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ChunkerInputError(f"{document_json_path} is not valid UTF-8: {exc}") from exc

    try:
        json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise ChunkerInputError(f"{document_json_path} is not valid JSON: {exc}") from exc

    try:
        document = DoclingDocument.load_from_json(document_json_path)
    except Exception as exc:  # noqa: BLE001 - any reload failure must become an actionable ChunkerInputError
        raise ChunkerInputError(
            f"{document_json_path} did not reload into the installed DoclingDocument model "
            f"({type(exc).__name__}: {exc}). It may have been produced by an incompatible "
            "Docling version, or is not a canonical parser document.json."
        ) from exc

    if not document.pages:
        raise ChunkerInputError(
            f"{document_json_path} reloaded with zero pages; refusing to chunk an empty document."
        )

    run_root = document_json_path.parent.parent
    manifest = _load_sibling_json(run_root / "run_manifest.json", "run_manifest.json")
    validation_report = _load_sibling_json(run_root / "validation" / "report.json", "validation/report.json")
    source_info = manifest.get("source", {}) if manifest else {}
    source_filename = source_info.get("filename") or (
        document.origin.filename if document.origin else document.name
    )
    source_sha256 = source_info.get("sha256")
    if source_sha256 is None:
        # Docling's own `origin.binary_hash` is an internal int hash, not a
        # SHA-256 hex digest, so it is never used as a stand-in here. Fall
        # back to hashing document.json itself, so a standalone document.json
        # (no sibling run_manifest.json) still gets a deterministic identity.
        source_sha256 = sha256_file(document_json_path)
        logger.warning(
            "No source SHA-256 available from a sibling run_manifest.json; using the hash of "
            "document.json itself (%s) as the document identity instead.",
            document_json_path,
        )
    source_sha256 = str(source_sha256)

    identity = SourceIdentity(
        document_json_path=document_json_path,
        document_json_sha256=sha256_file(document_json_path),
        source_filename=str(source_filename),
        source_sha256=source_sha256,
        run_manifest=manifest,
        validation_report=validation_report,
    )
    logger.info(
        "Loaded %s: %d pages, source=%s sha256=%s…",
        document_json_path,
        len(document.pages),
        identity.source_filename,
        identity.source_sha256[:12],
    )
    return document, identity

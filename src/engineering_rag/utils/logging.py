"""Centralized ``logging`` configuration for the whole application.

Configured **once**, at the application boundary (:mod:`engineering_rag.api.cli`).
Every other module — services, pipelines, utils — only ever does::

    import logging
    logger = logging.getLogger(__name__)

and never calls :func:`logging.basicConfig`. This module owns handler
installation so that repeated CLI invocations (or repeated imports inside a
test process) never accumulate duplicate handlers, and so a single place
decides what goes to the console, to a per-run file, and — optionally — to a
structured JSONL stream.

This is deliberately separate from
:class:`engineering_rag.services.parser.artifacts.JsonlLogger`, which records
*domain* pipeline events (``run_started``, ``conversion_complete``, ...) into
``logs/run.jsonl`` and predates this module. The two are complementary, not
redundant: this module is for operational/diagnostic logging of what the code
is doing; ``JsonlLogger`` is a structured record of what the *pipeline*
decided. Nothing here duplicates or replaces it.

Never log full extracted document text, table content, credentials, tokens,
secrets, or a complete serialised model object — only short, evidence-shaped
summaries (counts, paths, hashes, status strings), matching the redaction
policy already enforced elsewhere in the parser service.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "RunContextFilter",
    "attach_run_file_handler",
    "bind_run_context",
    "configure_logging",
    "current_context",
    "detach_handler",
]

_ROOT_LOGGER_NAME = "engineering_rag"
_CONSOLE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_FILE_FORMAT = (
    "%(asctime)s %(levelname)-8s %(name)s [run=%(run_id)s doc=%(document_id)s stage=%(stage)s]: %(message)s"
)

_active_context: RunContextFilter | None = None


class RunContextFilter(logging.Filter):
    """Attaches ``run_id`` / ``document_id`` / ``stage`` to every record it sees.

    One instance is shared by every handler `configure_logging` installs, so
    calling :func:`bind_run_context` once updates what every future log line
    — console, per-run file, JSONL — carries, without changing any of the
    existing ``logger.info(...)`` call sites throughout the codebase.
    """

    def __init__(self) -> None:
        super().__init__()
        self.run_id = ""
        self.document_id = ""
        self.stage = ""

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = getattr(record, "run_id", "") or self.run_id
        record.document_id = getattr(record, "document_id", "") or self.document_id
        record.stage = getattr(record, "stage", "") or self.stage
        return True


class _JsonlFormatter(logging.Formatter):
    """One JSON object per line: timestamp, level, logger, message, context, exception."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("run_id", "document_id", "stage"):
            value = getattr(record, key, "")
            if value:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _level(name: str) -> int:
    value = logging.getLevelName(str(name).upper())
    return value if isinstance(value, int) else logging.INFO


def configure_logging(
    *,
    console_level: str = "INFO",
    quiet_console: bool = False,
    log_file: Path | str | None = None,
    file_level: str = "DEBUG",
    jsonl: bool = False,
) -> RunContextFilter:
    """(Re-)configure the ``engineering_rag`` logger tree.

    Idempotent: any handler a previous call installed is removed first, so
    invoking this repeatedly (once per CLI command, or repeatedly inside a
    test process) never duplicates log lines. Returns the shared
    :class:`RunContextFilter` so a caller can bind run/document/stage context
    as it becomes known.

    Args:
        console_level: minimum level written to stderr. Default ``INFO``.
        quiet_console: force the console handler to ``ERROR`` only (used by
            ``--json`` output modes, so stdout stays machine-parseable).
        log_file: optional explicit file to also log to (in addition to any
            per-run file a pipeline attaches with :func:`attach_run_file_handler`).
        file_level: minimum level written to ``log_file``. Default ``DEBUG``.
        jsonl: write ``log_file`` as one JSON object per line instead of plain text.
    """
    global _active_context

    root = logging.getLogger(_ROOT_LOGGER_NAME)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.setLevel(logging.DEBUG)  # handlers do their own level filtering
    root.propagate = False

    context = RunContextFilter()
    _active_context = context

    console_handler = logging.StreamHandler(stream=sys.stderr)
    console_handler.setLevel(logging.ERROR if quiet_console else _level(console_level))
    console_handler.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
    console_handler.addFilter(context)
    root.addHandler(console_handler)

    if log_file is not None:
        _add_file_handler(root, Path(log_file), file_level, jsonl, context)

    return context


def attach_run_file_handler(
    path: Path | str, *, level: str = "DEBUG", jsonl: bool = False
) -> logging.Handler:
    """Attach a per-run file handler to the ``engineering_rag`` logger tree.

    Used by the parsing pipeline once a run directory exists, so every
    completed run carries its own operational log under ``logs/`` in addition
    to the console output. Pair with :func:`detach_handler` when the run ends
    so handlers do not accumulate across runs in a long-lived process.
    """
    root = logging.getLogger(_ROOT_LOGGER_NAME)
    return _add_file_handler(root, Path(path), level, jsonl, _active_context)


def detach_handler(handler: logging.Handler) -> None:
    """Remove and close a handler previously returned by :func:`attach_run_file_handler`."""
    logging.getLogger(_ROOT_LOGGER_NAME).removeHandler(handler)
    handler.close()


def _add_file_handler(
    root: logging.Logger, path: Path, level: str, jsonl: bool, context: RunContextFilter | None
) -> logging.Handler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(_level(level))
    handler.setFormatter(_JsonlFormatter() if jsonl else logging.Formatter(_FILE_FORMAT))
    if context is not None:
        handler.addFilter(context)
    root.addHandler(handler)
    return handler


def current_context() -> RunContextFilter:
    """The active :class:`RunContextFilter`, creating an unattached one if logging was never configured.

    Safe to call from library code (e.g. the pipeline) even when the caller
    never invoked :func:`configure_logging` — the returned filter simply has
    no handler attached yet, so binding context on it is a harmless no-op.
    """
    global _active_context
    if _active_context is None:
        _active_context = RunContextFilter()
    return _active_context


def bind_run_context(
    context: RunContextFilter,
    *,
    run_id: str | None = None,
    document_id: str | None = None,
    stage: str | None = None,
) -> None:
    """Update the run/document/stage fields every subsequent log record will carry."""
    if run_id is not None:
        context.run_id = run_id
    if document_id is not None:
        context.document_id = document_id
    if stage is not None:
        context.stage = stage

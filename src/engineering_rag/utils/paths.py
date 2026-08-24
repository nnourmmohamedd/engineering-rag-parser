"""Generic, service-agnostic path safety and default-root helpers.

Nothing here is parser-specific: :func:`safe_filename` and
:class:`UnsafePathError` are the path-traversal guard every service's
run-directory abstraction needs, and the ``default_*_root`` functions give
every service the same ``data/input`` / ``data/output/<service>`` layout
without hardcoding it more than once.

Roots are computed **lazily** (a plain function call, never a module-level
constant) so nothing here depends on the working directory at import time —
only at the moment a caller actually asks for a path, exactly like every
other relative path this project writes.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "UnsafePathError",
    "default_chunker_output_root",
    "default_input_root",
    "default_output_root",
    "default_parser_output_root",
    "repo_root",
    "safe_filename",
]

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_RESERVED_WINDOWS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class UnsafePathError(ValueError):
    """Raised when a requested artifact path would escape its intended root."""


def safe_filename(name: str, *, fallback: str = "item", max_length: int = 120) -> str:
    """Reduce arbitrary text to a portable, safe filename component.

    Handles the three things that actually bite on Windows: reserved device
    names (``CON``, ``NUL``), trailing dots/spaces, and path separators smuggled
    in through document-derived text.
    """
    cleaned = _UNSAFE_CHARS.sub("-", name.strip()).strip("-._")
    cleaned = cleaned[:max_length].rstrip("-._")
    if not cleaned:
        return fallback
    if cleaned.split(".")[0].upper() in _RESERVED_WINDOWS:
        cleaned = f"_{cleaned}"
    return cleaned


def repo_root(start: Path | None = None) -> Path:
    """Locate the repository root by walking up from ``start`` for ``pyproject.toml``.

    Defaults to walking up from this file's own location rather than the
    working directory, so it resolves correctly regardless of where a caller
    (CLI, test, notebook) happens to be invoked from. Falls back to the
    current working directory if no marker is found (e.g. an installed wheel
    with no source checkout nearby).
    """
    here = (start or Path(__file__)).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return Path.cwd()


def default_input_root() -> Path:
    """Default location for source documents supplied to any service."""
    return Path("data/input")


def default_output_root() -> Path:
    """Default location for all generated outputs."""
    return Path("data/output")


def default_parser_output_root() -> Path:
    """Default location for ``services/parser`` run artifacts."""
    return default_output_root() / "parser"


def default_chunker_output_root() -> Path:
    """Default location for the future ``services/chunker`` run artifacts."""
    return default_output_root() / "chunker"

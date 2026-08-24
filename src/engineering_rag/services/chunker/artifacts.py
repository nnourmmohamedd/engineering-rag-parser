"""Immutable chunker run directories and atomic output writes.

Mirrors the parser's ``services/parser/artifacts.py`` conventions (immutable,
timestamp+hash-named run directories; every write path-checked against the
run root) but is deliberately its own, smaller module: the chunker's output
shape (``chunks.jsonl`` + 3 report files) does not need the parser's
elaborate ``SUBDIRS`` layout.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engineering_rag.utils.paths import UnsafePathError, safe_filename

__all__ = ["ChunkerRunDirectory"]

logger = logging.getLogger(__name__)


@dataclass
class ChunkerRunDirectory:
    """An immutable artifact directory for one chunking run."""

    root: Path
    created_at: datetime

    @classmethod
    def create(
        cls, base: Path, document_stem: str, source_sha256: str, *, now: datetime | None = None
    ) -> ChunkerRunDirectory:
        """Create ``<base>/<stem>/<timestamp>-<short_sha>/``.

        Raises:
            FileExistsError: if the directory already exists — runs are immutable.
        """
        stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
        root = Path(base) / safe_filename(document_stem) / f"{stamp}-{source_sha256[:8]}"
        root.mkdir(parents=True, exist_ok=False)
        (root / "logs").mkdir(parents=True, exist_ok=True)
        logger.info("Chunker run directory: %s", root)
        return cls(root=root, created_at=now or datetime.now(timezone.utc))

    def path_for(self, *parts: str) -> Path:
        """Resolve a path inside the run directory, refusing escapes."""
        candidate = self.root.joinpath(*parts)
        resolved = candidate.resolve()
        root_resolved = self.root.resolve()
        if resolved != root_resolved and root_resolved not in resolved.parents:
            raise UnsafePathError(
                f"Refusing to write outside the run directory: {candidate} resolves to {resolved}"
            )
        return candidate

    def write_text_atomic(self, relative: str, text: str) -> Path:
        """Write UTF-8 text atomically: write to a temp file, then rename into place."""
        path = self.path_for(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        with tmp_path.open("w", encoding="utf-8", newline="") as fh:
            fh.write(normalized)
        tmp_path.replace(path)
        return path

    def write_json_atomic(self, relative: str, payload: Any, *, indent: int = 2) -> Path:
        """Write JSON deterministically (sorted keys, LF endings, UTF-8) and atomically."""
        text = json.dumps(payload, indent=indent, sort_keys=True, ensure_ascii=False, default=str)
        return self.write_text_atomic(relative, text + "\n")

    def write_jsonl_atomic(self, relative: str, records: list[dict[str, Any]]) -> Path:
        """Write newline-delimited JSON atomically, one compact object per line."""
        lines = [json.dumps(r, sort_keys=True, ensure_ascii=False, default=str) for r in records]
        return self.write_text_atomic(relative, "\n".join(lines) + ("\n" if lines else ""))

    def relative(self, path: Path) -> str:
        """POSIX-style path relative to the run root."""
        return path.resolve().relative_to(self.root.resolve()).as_posix()

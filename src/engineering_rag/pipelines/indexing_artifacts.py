"""Immutable indexing run directories and atomic output writes.

Mirrors ``services/chunker/artifacts.py`` exactly (immutable, timestamp+hash
run directories; every write path-checked against the run root), but the
directory this points at is a *report* directory
(``data/output/indexing/<collection>/<run-id>/``) — separate and independent
from the Chroma *persistence* directory itself
(``data/output/databases/chroma/<index-name>/``), which is stable across runs
and never per-run.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engineering_rag.utils.paths import UnsafePathError, safe_filename

__all__ = ["IndexRunDirectory"]

logger = logging.getLogger(__name__)


@dataclass
class IndexRunDirectory:
    """An immutable artifact directory for one indexing run."""

    root: Path
    created_at: datetime

    @classmethod
    def create(
        cls, base: Path, collection_name: str, input_hash: str, *, now: datetime | None = None
    ) -> IndexRunDirectory:
        """Create ``<base>/<collection>/<timestamp>-<short_hash>/``.

        Raises:
            FileExistsError: if the directory already exists — runs are immutable.
        """
        stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
        root = Path(base) / safe_filename(collection_name) / f"{stamp}-{input_hash[:8]}"
        root.mkdir(parents=True, exist_ok=False)
        (root / "logs").mkdir(parents=True, exist_ok=True)
        logger.info("Index run directory: %s", root)
        return cls(root=root, created_at=now or datetime.now(timezone.utc))

    def path_for(self, *parts: str) -> Path:
        candidate = self.root.joinpath(*parts)
        resolved = candidate.resolve()
        root_resolved = self.root.resolve()
        if resolved != root_resolved and root_resolved not in resolved.parents:
            raise UnsafePathError(
                f"Refusing to write outside the run directory: {candidate} resolves to {resolved}"
            )
        return candidate

    def write_text_atomic(self, relative: str, text: str) -> Path:
        path = self.path_for(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        with tmp_path.open("w", encoding="utf-8", newline="") as fh:
            fh.write(normalized)
        tmp_path.replace(path)
        return path

    def write_json_atomic(self, relative: str, payload: Any, *, indent: int = 2) -> Path:
        text = json.dumps(payload, indent=indent, sort_keys=True, ensure_ascii=False, default=str)
        return self.write_text_atomic(relative, text + "\n")

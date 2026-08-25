"""Immutable retrieval/evaluation run directories and atomic output writes.

Mirrors ``pipelines/indexing_artifacts.py`` exactly. A run directory here
(``data/output/retrieval/<RUN_ID>/``) is a report directory only — it never
touches the Chroma persistence directory itself, and creating one has no
effect on any collection.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engineering_rag.utils.paths import UnsafePathError

__all__ = ["RetrievalRunDirectory"]

logger = logging.getLogger(__name__)


@dataclass
class RetrievalRunDirectory:
    """An immutable artifact directory for one retrieval search or evaluation run."""

    root: Path
    created_at: datetime

    @classmethod
    def create(cls, base: Path, *, now: datetime | None = None) -> RetrievalRunDirectory:
        """Create ``<base>/<timestamp>-<short-uuid>/``. Never overwrites an earlier run.

        Raises:
            FileExistsError: if the directory already exists (practically
                unreachable given the uuid suffix, but never silently reused).
        """
        moment = now or datetime.now(timezone.utc)
        stamp = moment.strftime("%Y%m%dT%H%M%SZ")
        root = Path(base) / f"{stamp}-{uuid.uuid4().hex[:8]}"
        root.mkdir(parents=True, exist_ok=False)
        (root / "logs").mkdir(parents=True, exist_ok=True)
        logger.info("Retrieval run directory: %s", root)
        return cls(root=root, created_at=moment)

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

    def write_jsonl_atomic(self, relative: str, rows: list[Any]) -> Path:
        lines = [json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) for row in rows]
        return self.write_text_atomic(relative, "\n".join(lines) + ("\n" if lines else ""))

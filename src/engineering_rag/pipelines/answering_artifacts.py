"""Immutable answering run directories and atomic output writes.

Mirrors ``pipelines/retrieval_artifacts.py`` exactly. A run directory here
(``data/output/answering/<RUN_ID>/``) is a report directory only.
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

__all__ = ["AnsweringRunDirectory"]

logger = logging.getLogger(__name__)


@dataclass
class AnsweringRunDirectory:
    """An immutable artifact directory for one ``engrag-ask ask``/``evaluate`` run."""

    root: Path
    created_at: datetime

    @classmethod
    def create(
        cls, base: Path, *, run_id: str | None = None, now: datetime | None = None
    ) -> AnsweringRunDirectory:
        """Create ``<base>/<timestamp>-<short-uuid>/`` (or ``<base>/<run_id>/`` if given).

        Raises:
            FileExistsError: if the directory already exists.
        """
        moment = now or datetime.now(timezone.utc)
        if run_id is not None:
            root = Path(base) / run_id
        else:
            stamp = moment.strftime("%Y%m%dT%H%M%SZ")
            root = Path(base) / f"{stamp}-{uuid.uuid4().hex[:8]}"
        root.mkdir(parents=True, exist_ok=False)
        (root / "logs").mkdir(parents=True, exist_ok=True)
        logger.info("Answering run directory: %s", root)
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

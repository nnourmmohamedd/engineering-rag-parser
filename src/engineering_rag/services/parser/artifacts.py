"""Immutable run directories, safe path handling and the run manifest.

Two invariants this module exists to guarantee:

1. **A run never overwrites a previous run.** The directory name carries a UTC
   timestamp and the source hash, and creation uses ``exist_ok=False``.
2. **Nothing escapes the run directory.** Every write goes through
   :meth:`RunDirectory.path_for`, which resolves the candidate and rejects any
   path that lands outside the run root. The source PDF is untrusted, and a
   caption or filename derived from it must never be able to steer a write into
   ``~/.ssh`` via ``../..``.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engineering_rag.utils.hashing import sha256_file
from engineering_rag.utils.paths import UnsafePathError, safe_filename

from . import PARSER_VERSION

__all__ = [
    "RunDirectory",
    "RunManifest",
    "build_run_manifest",
]

logger = logging.getLogger(__name__)


@dataclass
class RunDirectory:
    """An immutable artifact directory for a single run.

    Layout matches the canonical tree: ``source/``, ``docling/``, ``markdown/``,
    ``assets/``, ``validation/``, ``logs/``.
    """

    root: Path
    created_at: datetime

    #: Subdirectories created eagerly so writers never race on mkdir.
    SUBDIRS = (
        "source",
        "docling",
        "markdown",
        "assets/pictures",
        "assets/pages",
        "validation",
        "validation/review",
        "logs",
    )

    @classmethod
    def create(
        cls,
        base: Path,
        source_stem: str,
        source_sha256: str,
        *,
        now: datetime | None = None,
        quarantine: bool = False,
    ) -> RunDirectory:
        """Create ``<base>/<stem>/<timestamp>-<short_sha>/`` and its subdirectories.

        Args:
            quarantine: route the run under ``quarantine/`` instead of
                ``artifacts/``. Used for partial/failed conversions so that a
                broken run can never be mistaken for a usable one.

        Raises:
            FileExistsError: if the directory already exists — runs are immutable.
        """
        stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
        parent = (base.parent / "quarantine") if quarantine else base
        root = parent / safe_filename(source_stem) / f"{stamp}-{source_sha256[:8]}"
        root.mkdir(parents=True, exist_ok=False)
        for sub in cls.SUBDIRS:
            (root / sub).mkdir(parents=True, exist_ok=True)
        logger.info("Run directory: %s", root)
        return cls(root=root, created_at=now or datetime.now(timezone.utc))

    def path_for(self, *parts: str) -> Path:
        """Resolve a path inside the run directory, refusing escapes.

        Raises:
            UnsafePathError: if the resolved path is not under :attr:`root`.
        """
        candidate = self.root.joinpath(*parts)
        resolved = candidate.resolve()
        root_resolved = self.root.resolve()
        if resolved != root_resolved and root_resolved not in resolved.parents:
            raise UnsafePathError(
                f"Refusing to write outside the run directory: {candidate} resolves to {resolved}"
            )
        return candidate

    def write_text(self, relative: str, text: str, *, newline: str = "\n") -> Path:
        """Write UTF-8 text with explicit LF endings.

        ``newline=""`` on the file object disables Python's translation, so the
        artifact is byte-identical on Windows and Linux — a prerequisite for the
        determinism check and for stable artifact hashes.
        """
        path = self.path_for(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        if newline != "\n":
            normalized = normalized.replace("\n", newline)
        with path.open("w", encoding="utf-8", newline="") as fh:
            fh.write(normalized)
        return path

    def write_json(self, relative: str, payload: Any, *, indent: int = 2) -> Path:
        """Write JSON deterministically (sorted keys, LF endings, UTF-8)."""
        text = json.dumps(payload, indent=indent, sort_keys=True, ensure_ascii=False, default=_json_default)
        return self.write_text(relative, text + "\n")

    def write_bytes(self, relative: str, data: bytes) -> Path:
        """Write binary data (image assets) inside the run directory."""
        path = self.path_for(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def relative(self, path: Path) -> str:
        """POSIX-style path relative to the run root.

        Always forward slashes: these strings go into Markdown links and JSON
        manifests that must work regardless of the OS that produced them.
        """
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    def hash_artifacts(self) -> dict[str, str]:
        """SHA-256 of every file in the run, keyed by relative POSIX path.

        The manifest itself is excluded — it cannot contain its own hash.
        """
        out: dict[str, str] = {}
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and path.name != "run_manifest.json":
                out[self.relative(path)] = sha256_file(path)
        return out


def _json_default(obj: Any) -> Any:
    """Serialise the few non-JSON types that reach the manifest."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return obj.as_posix()
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serialisable")


@dataclass
class RunManifest:
    """Everything needed to reproduce, audit or invalidate a run."""

    run_id: str
    parser_version: str
    generated_at_utc: str
    source: dict[str, Any]
    config_hash: str
    effective_config: dict[str, Any]
    profile: str
    profile_reason: str
    profile_evidence: dict[str, Any] = field(default_factory=dict)
    docling: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    timings_s: dict[str, float] = field(default_factory=dict)
    conversion: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    status: str = "FAIL"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


def environment_snapshot() -> dict[str, Any]:
    """Portable description of the machine that produced a run.

    Deliberately excludes hostname, user and absolute paths: the manifest is a
    shareable artifact and must not carry machine-identifying detail.
    """
    return {
        "python_version": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count() or 0,
    }


def build_run_manifest(
    *,
    run: RunDirectory,
    source_manifest_data: dict[str, Any],
    config_hash: str,
    effective_config: dict[str, Any],
    profile: str,
    profile_reason: str,
    profile_evidence: dict[str, Any],
    docling_info: dict[str, Any],
    timings: dict[str, float],
    conversion: dict[str, Any],
    status: str,
    warnings: list[str],
) -> RunManifest:
    """Assemble the run manifest, hashing every artifact produced so far."""
    return RunManifest(
        run_id=run.root.name,
        parser_version=PARSER_VERSION,
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        source={
            "filename": source_manifest_data.get("filename"),
            "sha256": source_manifest_data.get("sha256"),
            "byte_size": source_manifest_data.get("byte_size"),
            "page_count": source_manifest_data.get("page_count"),
            "pdf_version": source_manifest_data.get("pdf_version"),
        },
        config_hash=config_hash,
        effective_config=effective_config,
        profile=profile,
        profile_reason=profile_reason,
        profile_evidence=profile_evidence,
        docling=docling_info,
        environment=environment_snapshot(),
        timings_s={k: round(v, 3) for k, v in timings.items()},
        conversion=conversion,
        artifacts=run.hash_artifacts(),
        status=status,
        warnings=warnings,
    )


class JsonlLogger:
    """Append-only structured run log (``logs/run.jsonl``).

    One JSON object per line so the log stays greppable and machine-readable
    without a parser, and so a crash mid-run still leaves valid earlier lines.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, **fields: Any) -> None:
        """Append one event record."""
        record = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        line = json.dumps(record, ensure_ascii=False, default=_json_default, sort_keys=True)
        with self.path.open("a", encoding="utf-8", newline="") as fh:
            fh.write(line + "\n")

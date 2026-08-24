"""Immutable chunker run directory and atomic-write tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from engineering_rag.services.chunker.artifacts import ChunkerRunDirectory
from engineering_rag.utils.paths import UnsafePathError


class TestChunkerRunDirectory:
    def test_run_id_carries_timestamp_and_hash(self, tmp_path: Path) -> None:
        now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        run = ChunkerRunDirectory.create(tmp_path / "a", "doc", "abcdef12" + "0" * 56, now=now)
        assert run.root.name == "20260102T030405Z-abcdef12"

    def test_runs_are_immutable(self, tmp_path: Path) -> None:
        now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        ChunkerRunDirectory.create(tmp_path / "a", "doc", "a" * 64, now=now)
        with pytest.raises(FileExistsError):
            ChunkerRunDirectory.create(tmp_path / "a", "doc", "a" * 64, now=now)

    def test_path_traversal_is_refused(self, tmp_path: Path) -> None:
        run = ChunkerRunDirectory.create(tmp_path / "a", "doc", "a" * 64)
        with pytest.raises(UnsafePathError):
            run.path_for("../evil.txt")

    def test_write_text_atomic_produces_final_content_only(self, tmp_path: Path) -> None:
        run = ChunkerRunDirectory.create(tmp_path / "a", "doc", "a" * 64)
        path = run.write_text_atomic("chunks.jsonl", "line one\r\nline two\n")
        raw = path.read_bytes()
        assert b"\r" not in raw
        assert not path.with_suffix(path.suffix + ".tmp").exists()

    def test_write_json_atomic_is_deterministic(self, tmp_path: Path) -> None:
        run = ChunkerRunDirectory.create(tmp_path / "a", "doc", "a" * 64)
        p1 = run.write_json_atomic("manifest.json", {"b": 2, "a": 1})
        first = p1.read_bytes()
        p2 = run.write_json_atomic("manifest.json", {"a": 1, "b": 2})
        assert p2.read_bytes() == first

    def test_write_jsonl_atomic_one_object_per_line(self, tmp_path: Path) -> None:
        run = ChunkerRunDirectory.create(tmp_path / "a", "doc", "a" * 64)
        path = run.write_jsonl_atomic("chunks.jsonl", [{"a": 1}, {"b": 2}])
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_relative_uses_posix_separators(self, tmp_path: Path) -> None:
        run = ChunkerRunDirectory.create(tmp_path / "a", "doc", "a" * 64)
        path = run.write_text_atomic("logs/chunker.log", "hi")
        assert run.relative(path) == "logs/chunker.log"

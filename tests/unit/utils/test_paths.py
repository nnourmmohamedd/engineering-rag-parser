"""Unit tests for generic path-safety and default-root helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_rag.utils.paths import (
    default_chunker_output_root,
    default_input_root,
    default_output_root,
    default_parser_output_root,
    repo_root,
    safe_filename,
)


class TestSafeFilename:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Table 1: Deliverables", "Table-1-Deliverables"),
            ("../../etc/passwd", "etc-passwd"),
            ("a/b\\c", "a-b-c"),
            ("", "item"),
            ("...", "item"),
        ],
    )
    def test_sanitises(self, raw: str, expected: str) -> None:
        assert safe_filename(raw) == expected

    def test_windows_reserved_names_are_escaped(self) -> None:
        assert safe_filename("CON") == "_CON"
        assert safe_filename("nul.txt") == "_nul.txt"

    def test_length_is_bounded(self) -> None:
        assert len(safe_filename("x" * 500)) <= 120


class TestDefaultRoots:
    def test_input_root(self) -> None:
        assert default_input_root() == Path("data/input")

    def test_output_root(self) -> None:
        assert default_output_root() == Path("data/output")

    def test_parser_output_root(self) -> None:
        assert default_parser_output_root() == Path("data/output/parser")

    def test_chunker_output_root(self) -> None:
        assert default_chunker_output_root() == Path("data/output/chunker")

    def test_roots_are_computed_fresh_each_call(self) -> None:
        """Not a cached module-level constant frozen at import time."""
        assert default_parser_output_root() is not default_parser_output_root()
        assert default_parser_output_root() == default_parser_output_root()


class TestRepoRoot:
    def test_finds_pyproject_toml(self) -> None:
        root = repo_root()
        assert (root / "pyproject.toml").is_file()

    def test_does_not_depend_on_the_working_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        root = repo_root()
        assert (root / "pyproject.toml").is_file()

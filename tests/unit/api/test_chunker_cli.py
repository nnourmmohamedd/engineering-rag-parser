"""CLI tests for ``engrag-chunk``: exit codes, help, inspect/validate on stored artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from engineering_rag.api.chunker_cli import app
from engineering_rag.services.chunker import CHUNKER_VERSION

runner = CliRunner()


class TestVersionAndHelp:
    def test_version(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert CHUNKER_VERSION in result.stdout

    def test_no_args_shows_help(self) -> None:
        result = runner.invoke(app, [])
        assert "run" in result.output

    def test_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    @pytest.mark.parametrize("cmd", ["run", "inspect", "validate"])
    def test_subcommand_help(self, cmd: str) -> None:
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code == 0


class TestRunCommand:
    def test_missing_input_is_rejected_by_typer(self) -> None:
        result = runner.invoke(app, ["run", "--input", "does-not-exist.json"])
        assert result.exit_code == 2

    def test_malformed_input_exits_2(self, tmp_path: Path) -> None:
        bad = tmp_path / "document.json"
        bad.write_text("not json", encoding="utf-8")
        result = runner.invoke(app, ["run", "--input", str(bad), "--output", str(tmp_path / "out")])
        assert result.exit_code == 2
        assert "Input rejected" in result.output


class TestInspectAndValidateOnMissingInput:
    def test_inspect_missing_file_exits_2(self) -> None:
        result = runner.invoke(app, ["inspect", "--input", "no-such-chunks.jsonl"])
        assert result.exit_code == 2

    def test_validate_missing_report_exits_2(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["validate", "--input", str(tmp_path)])
        assert result.exit_code == 2


class TestInspectCommand:
    def test_reports_chunk_statistics(self, tmp_path: Path) -> None:
        jsonl = tmp_path / "chunks.jsonl"
        records = [
            {"content_type": "text", "token_count": 10},
            {"content_type": "text", "token_count": 20},
            {"content_type": "table", "token_count": 15},
        ]
        jsonl.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        result = runner.invoke(app, ["inspect", "--input", str(jsonl), "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["chunk_count"] == 3
        assert payload["content_type_counts"]["text"] == 2

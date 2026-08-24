"""CLI tests: exit codes, `--help`/`--version`, and command behaviour.

Uses Typer's in-process `CliRunner` rather than subprocess, so failures show a
readable traceback and coverage instrumentation sees the CLI module. `run`
needs a real Docling conversion, so its tests are gated on cached model
weights like the rest of the integration suite.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from engineering_rag import __version__
from engineering_rag.api.cli import _force_utf8_streams, app
from engineering_rag.pipelines.parsing_pipeline import run_parsing_pipeline
from engineering_rag.services.parser.config import ParserConfig, Profile

from ...conftest import requires_docling_models

runner = CliRunner()


class TestForceUtf8Streams:
    """Regression test: a legacy-codepage Windows console (e.g. cp1256) raised an
    unhandled `UnicodeEncodeError` from inside Rich when the CLI printed an
    arrow or warning glyph, turning `validate --strict` into a stack trace
    instead of the intended exit code. `_force_utf8_streams` must reconfigure
    stdout/stderr to UTF-8 and never itself raise, even when a stream refuses
    to be reconfigured.
    """

    def test_does_not_raise_when_a_stream_has_no_reconfigure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _NoReconfigure:
            pass

        monkeypatch.setattr("sys.stdout", _NoReconfigure())
        monkeypatch.setattr("sys.stderr", _NoReconfigure())
        _force_utf8_streams()  # must not raise

    def test_does_not_raise_when_reconfigure_itself_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _HostileStream:
            def reconfigure(self, **_kwargs: object) -> None:
                raise ValueError("stream does not support reconfiguration")

        monkeypatch.setattr("sys.stdout", _HostileStream())
        monkeypatch.setattr("sys.stderr", _HostileStream())
        _force_utf8_streams()  # must not raise

    def test_reconfigures_real_streams_to_utf8(self) -> None:
        _force_utf8_streams()
        assert (sys.stdout.encoding or "").lower().replace("-", "") == "utf8"


class TestVersionAndHelp:
    def test_version(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.stdout

    def test_no_args_shows_help(self) -> None:
        result = runner.invoke(app, [])
        assert "inspect" in result.output

    def test_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    @pytest.mark.parametrize("cmd", ["inspect", "run", "validate", "show"])
    def test_subcommand_help(self, cmd: str) -> None:
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code == 0


class TestInspectCommand:
    def test_missing_file_is_rejected_by_typer(self) -> None:
        """`exists=True` on the Typer option rejects a nonexistent path before any pipeline code runs."""
        result = runner.invoke(app, ["inspect", "--input", "does-not-exist.pdf"])
        assert result.exit_code == 2

    def test_non_pdf_is_rejected_by_preflight(self, tmp_path: Path) -> None:
        bad = tmp_path / "fake.pdf"
        bad.write_bytes(b"NOT A PDF")
        result = runner.invoke(app, ["inspect", "--input", str(bad)])
        assert result.exit_code == 2

    def test_reports_a_structured_pdf(self, structured_pdf: Path) -> None:
        result = runner.invoke(app, ["inspect", "--input", str(structured_pdf)])
        assert result.exit_code == 0
        assert "Preflight" in result.stdout

    def test_json_output_is_valid_json(self, structured_pdf: Path) -> None:
        result = runner.invoke(app, ["inspect", "--input", str(structured_pdf), "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["page_count"] == 3


class TestValidateAndShowOnMissingRun:
    def test_validate_missing_report_exits_2(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["validate", "--run", str(tmp_path)])
        assert result.exit_code == 2

    def test_show_missing_manifest_exits_2(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["show", "--run", str(tmp_path)])
        assert result.exit_code == 2

    def test_validate_run_option_requires_existing_directory(self) -> None:
        result = runner.invoke(app, ["validate", "--run", "no-such-dir"])
        assert result.exit_code == 2


@requires_docling_models
class TestEndToEndCliOnSyntheticPdf:
    @pytest.fixture(scope="class")
    @classmethod
    def completed_run(cls, structured_pdf: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
        artifacts = tmp_path_factory.mktemp("cli-artifacts")
        cfg = ParserConfig().with_overrides(profile=Profile.HIGH_FIDELITY)
        result = run_parsing_pipeline(structured_pdf, cfg, artifacts)
        return result.run_dir

    def test_validate_reports_pass_or_pass_with_warnings(self, completed_run: Path) -> None:
        result = runner.invoke(app, ["validate", "--run", str(completed_run), "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] in ("PASS", "PASS_WITH_WARNINGS")

    def test_validate_text_output(self, completed_run: Path) -> None:
        result = runner.invoke(app, ["validate", "--run", str(completed_run)])
        assert result.exit_code == 0
        assert "Validation checks" in result.stdout

    def test_show_prints_run_summary(self, completed_run: Path) -> None:
        result = runner.invoke(app, ["show", "--run", str(completed_run)])
        assert result.exit_code == 0
        assert "Docling" in result.stdout

    def test_run_command_produces_the_same_artifacts_as_the_library_call(
        self, structured_pdf: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        artifacts = tmp_path_factory.mktemp("cli-run")
        result = runner.invoke(
            app, ["run", "--input", str(structured_pdf), "--artifacts", str(artifacts), "--json"]
        )
        assert result.exit_code in (0, 1)  # PASS/PASS_WITH_WARNINGS -> 0, FAIL -> 1
        payload = json.loads(result.stdout)
        assert payload["exit_code"] == result.exit_code
        assert (Path(payload["run_dir"]) / "run_manifest.json").is_file()

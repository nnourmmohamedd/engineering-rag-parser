"""OCR/scanned-path failure modes: the CLI must fail loudly, never silently succeed.

Simulates the failures a real deployment can hit (OCR backend not installed,
OCR engine initialization error, a mid-conversion OCR failure) by raising from
`convert_pdf`, the single choke point `ParserService.run` calls into. This avoids a
slow real OCR conversion for every failure scenario while still proving the
CLI's actual error-handling contract: a non-zero exit code and a readable
message on stderr/stdout, never a fabricated PASS.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from engineering_rag.api.cli import app

runner = CliRunner()


class TestMissingOrFailingOcrBackend:
    def test_missing_ocr_dependency_fails_loudly_not_silently(
        self, monkeypatch: pytest.MonkeyPatch, image_only_pdf: Path, tmp_path: Path
    ) -> None:
        """`ImportError: easyocr`-style failure (extra not installed) must exit non-zero with a message."""

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise ImportError("No module named 'easyocr' -- install with pip install -e '.[ocr]'")

        monkeypatch.setattr("engineering_rag.services.parser.service.convert_pdf", _boom)
        result = runner.invoke(
            app,
            [
                "run",
                "--input",
                str(image_only_pdf),
                "--profile",
                "scanned",
                "--artifacts",
                str(tmp_path / "artifacts"),
            ],
        )
        assert result.exit_code == 3
        assert "easyocr" in result.output or "Run failed" in result.output
        assert "PASS" not in result.output

    def test_ocr_engine_initialization_failure_fails_loudly(
        self, monkeypatch: pytest.MonkeyPatch, image_only_pdf: Path, tmp_path: Path
    ) -> None:
        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("Failed to initialize OCR engine: model weights unavailable")

        monkeypatch.setattr("engineering_rag.services.parser.service.convert_pdf", _boom)
        result = runner.invoke(
            app,
            [
                "run",
                "--input",
                str(image_only_pdf),
                "--profile",
                "scanned",
                "--artifacts",
                str(tmp_path / "artifacts"),
            ],
        )
        assert result.exit_code == 3
        assert "Run failed" in result.output

    def test_ocr_conversion_failure_fails_loudly(
        self, monkeypatch: pytest.MonkeyPatch, image_only_pdf: Path, tmp_path: Path
    ) -> None:
        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("OCR conversion crashed mid-page")

        monkeypatch.setattr("engineering_rag.services.parser.service.convert_pdf", _boom)
        result = runner.invoke(
            app,
            [
                "run",
                "--input",
                str(image_only_pdf),
                "--profile",
                "scanned",
                "--artifacts",
                str(tmp_path / "artifacts"),
            ],
        )
        assert result.exit_code == 3
        assert "Run failed" in result.output

    def test_json_mode_also_fails_loudly_not_silently(
        self, monkeypatch: pytest.MonkeyPatch, image_only_pdf: Path, tmp_path: Path
    ) -> None:
        """Even with --json, a conversion failure must not print a fabricated success payload."""

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("OCR backend unavailable")

        monkeypatch.setattr("engineering_rag.services.parser.service.convert_pdf", _boom)
        result = runner.invoke(
            app,
            [
                "run",
                "--input",
                str(image_only_pdf),
                "--profile",
                "scanned",
                "--artifacts",
                str(tmp_path / "artifacts"),
                "--json",
            ],
        )
        assert result.exit_code == 3
        assert '"status": "PASS"' not in result.output
        assert '"status":"PASS"' not in result.output

    def test_no_run_directory_left_claiming_success_on_failure(
        self, monkeypatch: pytest.MonkeyPatch, image_only_pdf: Path, tmp_path: Path
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("OCR backend unavailable")

        monkeypatch.setattr("engineering_rag.services.parser.service.convert_pdf", _boom)
        runner.invoke(
            app,
            [
                "run",
                "--input",
                str(image_only_pdf),
                "--profile",
                "scanned",
                "--artifacts",
                str(artifacts_dir),
            ],
        )
        for manifest in artifacts_dir.rglob("run_manifest.json"):
            import json

            data = json.loads(manifest.read_text(encoding="utf-8"))
            assert data.get("status") not in ("PASS", "PASS_WITH_WARNINGS")

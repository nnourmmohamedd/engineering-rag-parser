"""CLI tests for ``engrag-index``: exit codes, help, and delegation to the pipeline.

``build``'s happy path is exercised with the real pipeline but a monkeypatched
default embedder factory (see ``_patch_default_embedder``), so this suite
never downloads the real BGE model — matching the CI-network-free convention
used by ``test_chunker_cli.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from engineering_rag.api.index_cli import app
from engineering_rag.services.embedder import EMBEDDER_VERSION
from tests.support.fake_embedder import FakeEmbeddingService

runner = CliRunner()

_TOKENIZER = "sentence-transformers/all-MiniLM-L6-v2"


def _write_chunk_run(tmp_path: Path, *, n: int = 3) -> Path:
    run_dir = tmp_path / "chunker_run"
    run_dir.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "schema_version": "1.0.0",
            "chunk_id": f"chunk_{i:04d}",
            "document_id": "docsha256",
            "source_filename": "doc.pdf",
            "source_sha256": "docsha256",
            "chunk_index": i,
            "content_type": "text",
            "text": f"Faithful content about pump {i}.",
            "retrieval_text": f"Faithful content about pump {i}.",
            "token_count": 6,
            "tokenizer_name": _TOKENIZER,
            "heading_path": [],
            "section_title": None,
            "captions": [],
            "labels": ["text"],
            "page_numbers": [1],
            "provenance": [],
            "source_element_refs": [],
            "parent_chunk_id": None,
            "previous_chunk_id": None,
            "next_chunk_id": None,
            "merged_from_chunk_ids": None,
            "split_method": "hierarchical",
            "was_recursively_split": False,
            "overlap_tokens_before": 0,
            "table_metadata": None,
            "figure_asset_path": None,
            "figure_page_no": None,
            "is_atomic_overflow": False,
            "parser_warnings": [],
            "warnings": [],
        }
        for i in range(n)
    ]
    (run_dir / "chunks.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    manifest = {
        "run_id": "20260101T000000Z-deadbeef",
        "tokenizer": {"name": _TOKENIZER, "max_tokens": 256},
        "source": {"filename": "doc.pdf", "sha256": "docsha256"},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "validation_report.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    return run_dir


def _write_profile(tmp_path: Path, collection: str = "cli_test") -> Path:
    profile = {
        "embedding": {"model_name": _TOKENIZER, "expected_dimension": 768, "maximum_sequence_length": 256},
        "chroma": {"persistence_path": str(tmp_path / "chroma"), "collection_name": collection},
        "output_root": str(tmp_path / "reports"),
    }
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(profile), encoding="utf-8")
    return path


class TestVersionAndHelp:
    def test_version(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert EMBEDDER_VERSION in result.stdout

    def test_no_args_shows_help(self) -> None:
        result = runner.invoke(app, [])
        assert "build" in result.output

    def test_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    @pytest.mark.parametrize("cmd", ["build", "inspect", "validate", "list", "smoke-query"])
    def test_subcommand_help(self, cmd: str) -> None:
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code == 0


class TestBuildCommand:
    def test_missing_input_is_rejected_by_typer(self) -> None:
        result = runner.invoke(app, ["build", "--input", "does-not-exist"])
        assert result.exit_code == 2

    def test_tokenizer_mismatch_exits_2(self, tmp_path: Path) -> None:
        run_dir = _write_chunk_run(tmp_path)
        manifest_path = run_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["tokenizer"]["name"] = "some/other-tokenizer"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        profile = _write_profile(tmp_path)

        result = runner.invoke(app, ["build", "--input", str(run_dir), "--profile", str(profile)])
        assert result.exit_code == 2
        assert "Input rejected" in result.output

    def test_happy_path_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        run_dir = _write_chunk_run(tmp_path)
        profile = _write_profile(tmp_path)

        import engineering_rag.api.index_cli as cli_module

        def _fake_run(input_path, config, *, rebuild=False):  # noqa: ANN001, ANN202
            from engineering_rag.pipelines.indexing_pipeline import run_indexing_pipeline as real_run

            return real_run(input_path, config, rebuild=rebuild, embedder=FakeEmbeddingService())

        monkeypatch.setattr(cli_module, "run_indexing_pipeline", _fake_run)

        result = runner.invoke(app, ["build", "--input", str(run_dir), "--profile", str(profile), "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["chunk_count"] == 3
        assert payload["collection_name"] == "cli_test"

    def test_rebuild_flag_prints_warning(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        run_dir = _write_chunk_run(tmp_path)
        profile = _write_profile(tmp_path)

        import engineering_rag.api.index_cli as cli_module

        def _fake_run(input_path, config, *, rebuild=False):  # noqa: ANN001, ANN202
            from engineering_rag.pipelines.indexing_pipeline import run_indexing_pipeline as real_run

            return real_run(input_path, config, rebuild=rebuild, embedder=FakeEmbeddingService())

        monkeypatch.setattr(cli_module, "run_indexing_pipeline", _fake_run)

        result = runner.invoke(
            app, ["build", "--input", str(run_dir), "--profile", str(profile), "--rebuild"]
        )
        assert "--rebuild" in result.output


class TestInspectCommand:
    def test_missing_collection_exits_2(self, tmp_path: Path) -> None:
        profile = _write_profile(tmp_path)
        result = runner.invoke(app, ["inspect", "--profile", str(profile), "--collection", "nope"])
        assert result.exit_code == 2
        assert "No such collection" in result.output


class TestValidateCommand:
    def test_missing_report_exits_2(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["validate", "--run", str(tmp_path)])
        assert result.exit_code == 2

    def test_valid_pass_report_exits_0(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone

        report = {
            "status": "PASS",
            "strict": False,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "checks": [],
            "human_review_items": [],
        }
        (tmp_path / "index_validation_report.json").write_text(json.dumps(report), encoding="utf-8")
        result = runner.invoke(app, ["validate", "--run", str(tmp_path)])
        assert result.exit_code == 0

    def test_fail_report_exits_1(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone

        report = {
            "status": "FAIL",
            "strict": False,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "checks": [
                {
                    "check_id": "x",
                    "title": "x",
                    "passed": False,
                    "severity": "CRITICAL",
                    "gate": True,
                    "summary": "",
                    "evidence": {},
                    "remediation": "",
                }
            ],
            "human_review_items": [],
        }
        (tmp_path / "index_validation_report.json").write_text(json.dumps(report), encoding="utf-8")
        result = runner.invoke(app, ["validate", "--run", str(tmp_path)])
        assert result.exit_code == 1


class TestListCommand:
    def test_list_empty_persistence_path(self, tmp_path: Path) -> None:
        profile = _write_profile(tmp_path)
        result = runner.invoke(app, ["list", "--profile", str(profile)])
        assert result.exit_code == 0

    def test_list_json(self, tmp_path: Path) -> None:
        profile = _write_profile(tmp_path)
        result = runner.invoke(app, ["list", "--profile", str(profile), "--json"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == []

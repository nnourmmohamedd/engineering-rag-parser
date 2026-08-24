"""Integration tests: document.json -> chunk pipeline -> validation -> artifacts.

Uses a synthetic DoclingDocument (no PDF, no Docling conversion needed) so
this suite runs without the confidential acceptance documents. Requires the
chunker tokenizer to be reachable/cached (network on first use).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from engineering_rag.pipelines.chunking_pipeline import run_chunking_pipeline
from engineering_rag.services.chunker import ChunkerConfig
from engineering_rag.services.chunker.models import RunStatus

from ....conftest import requires_chunker_tokenizer

pytestmark = [pytest.mark.integration, requires_chunker_tokenizer]


def _write_document_json(tmp_path: Path) -> Path:
    from tests.unit.services.chunker.conftest import build_sample_document

    doc = build_sample_document()
    dest = tmp_path / "run" / "docling" / "document.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    doc.save_as_json(dest)
    return dest.parent.parent


class TestFullPipeline:
    def test_run_produces_pass_or_warnings(self, tmp_path: Path) -> None:
        run_dir_input = _write_document_json(tmp_path)
        config = ChunkerConfig(output_root=tmp_path / "out")
        result = run_chunking_pipeline(run_dir_input, config)
        assert result.status in (RunStatus.PASS.value, RunStatus.PASS_WITH_WARNINGS.value)
        assert result.chunk_count > 0

    def test_all_expected_artifacts_exist(self, tmp_path: Path) -> None:
        run_dir_input = _write_document_json(tmp_path)
        config = ChunkerConfig(output_root=tmp_path / "out")
        result = run_chunking_pipeline(run_dir_input, config)
        for rel in (
            "chunks.jsonl",
            "manifest.json",
            "validation_report.json",
            "chunking_summary.md",
            "logs/chunker.log",
        ):
            assert (result.run_dir / rel).is_file(), rel

    def test_chunks_jsonl_is_valid_jsonl(self, tmp_path: Path) -> None:
        run_dir_input = _write_document_json(tmp_path)
        config = ChunkerConfig(output_root=tmp_path / "out")
        result = run_chunking_pipeline(run_dir_input, config)
        lines = (result.run_dir / "chunks.jsonl").read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == result.chunk_count
        for line in lines:
            json.loads(line)  # must not raise

    def test_second_run_does_not_overwrite_the_first(self, tmp_path: Path) -> None:
        # Run IDs carry second-resolution timestamps (matching the parser's
        # own RunDirectory convention); a >=1s gap avoids a same-second
        # collision so this test observes two genuinely distinct run
        # directories rather than exercising FileExistsError instead.
        run_dir_input = _write_document_json(tmp_path)
        config = ChunkerConfig(output_root=tmp_path / "out")
        first = run_chunking_pipeline(run_dir_input, config)
        time.sleep(1.1)
        second = run_chunking_pipeline(run_dir_input, config)
        assert first.run_dir != second.run_dir

    def test_repeated_runs_produce_byte_identical_chunks_jsonl(self, tmp_path: Path) -> None:
        run_dir_input = _write_document_json(tmp_path)
        config = ChunkerConfig(output_root=tmp_path / "out")
        first = run_chunking_pipeline(run_dir_input, config)
        time.sleep(1.1)
        second = run_chunking_pipeline(run_dir_input, config)
        first_bytes = (first.run_dir / "chunks.jsonl").read_bytes()
        second_bytes = (second.run_dir / "chunks.jsonl").read_bytes()
        assert first_bytes == second_bytes

    def test_manifest_hashes_match_generated_files(self, tmp_path: Path) -> None:
        from engineering_rag.utils.hashing import sha256_file

        run_dir_input = _write_document_json(tmp_path)
        config = ChunkerConfig(output_root=tmp_path / "out")
        result = run_chunking_pipeline(run_dir_input, config)
        manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["artifacts"]["chunks.jsonl"] == sha256_file(result.run_dir / "chunks.jsonl")
        assert manifest["artifacts"]["validation_report.json"] == sha256_file(
            result.run_dir / "validation_report.json"
        )

    def test_no_absolute_paths_in_output(self, tmp_path: Path) -> None:
        run_dir_input = _write_document_json(tmp_path)
        config = ChunkerConfig(output_root=tmp_path / "out")
        result = run_chunking_pipeline(run_dir_input, config)
        text = (result.run_dir / "chunks.jsonl").read_text(encoding="utf-8")
        assert str(tmp_path.resolve()) not in text

    def test_accepts_document_json_file_directly(self, tmp_path: Path) -> None:
        run_dir_input = _write_document_json(tmp_path)
        document_json = run_dir_input / "docling" / "document.json"
        config = ChunkerConfig(output_root=tmp_path / "out2")
        result = run_chunking_pipeline(document_json, config)
        assert result.chunk_count > 0

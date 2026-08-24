"""Input loading and validation tests: malformed input must fail loudly."""

from __future__ import annotations

from pathlib import Path

import pytest
from docling_core.types.doc import DoclingDocument

from engineering_rag.services.chunker.loader import (
    ChunkerInputError,
    load_document,
    resolve_document_json_path,
)

from .conftest import build_sample_document


def _write_document_json(doc: DoclingDocument, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save_as_json(path)
    return path


class TestResolveDocumentJsonPath:
    def test_accepts_a_direct_file(self, tmp_path: Path) -> None:
        path = _write_document_json(build_sample_document(), tmp_path / "document.json")
        assert resolve_document_json_path(path) == path

    def test_accepts_a_parser_run_directory(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        _write_document_json(build_sample_document(), run_dir / "docling" / "document.json")
        assert resolve_document_json_path(run_dir) == run_dir / "docling" / "document.json"

    def test_directory_without_document_json_raises(self, tmp_path: Path) -> None:
        (tmp_path / "empty").mkdir()
        with pytest.raises(ChunkerInputError, match="docling/document.json"):
            resolve_document_json_path(tmp_path / "empty")

    def test_missing_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ChunkerInputError, match="not found"):
            resolve_document_json_path(tmp_path / "nope.json")


class TestLoadDocument:
    def test_loads_a_valid_document(self, tmp_path: Path) -> None:
        path = _write_document_json(build_sample_document(), tmp_path / "document.json")
        doc, identity = load_document(path)
        assert len(doc.pages) == 3
        assert identity.document_json_sha256

    def test_standalone_document_gets_a_fallback_identity(self, tmp_path: Path) -> None:
        """No sibling run_manifest.json: identity falls back to hashing document.json itself."""
        path = _write_document_json(build_sample_document(), tmp_path / "document.json")
        _doc, identity = load_document(path)
        assert identity.source_sha256 == identity.document_json_sha256

    def test_not_json_raises_actionable_error(self, tmp_path: Path) -> None:
        path = tmp_path / "document.json"
        path.write_text("not json at all {{{", encoding="utf-8")
        with pytest.raises(ChunkerInputError, match="not valid JSON"):
            load_document(path)

    def test_valid_json_but_not_a_doclingdocument_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "document.json"
        path.write_text('{"hello": "world"}', encoding="utf-8")
        with pytest.raises(ChunkerInputError, match="did not reload"):
            load_document(path)

    def test_not_utf8_raises_actionable_error(self, tmp_path: Path) -> None:
        path = tmp_path / "document.json"
        path.write_bytes(b"\xff\xfe\x00\x01not utf8")
        with pytest.raises(ChunkerInputError, match="UTF-8"):
            load_document(path)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ChunkerInputError):
            load_document(tmp_path / "absent.json")

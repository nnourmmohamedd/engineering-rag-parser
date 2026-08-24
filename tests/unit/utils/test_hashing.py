"""Unit tests for the generic file-hashing helper."""

from __future__ import annotations

import hashlib
from pathlib import Path

from engineering_rag.utils.hashing import sha256_file


class TestSha256File:
    def test_matches_hashlib(self, tmp_path: Path) -> None:
        path = tmp_path / "f.bin"
        payload = b"engineering" * 1000
        path.write_bytes(payload)
        assert sha256_file(path) == hashlib.sha256(payload).hexdigest()

    def test_streams_in_chunks_without_loading_whole_file(self, tmp_path: Path) -> None:
        path = tmp_path / "f.bin"
        payload = b"x" * 10_000
        path.write_bytes(payload)
        assert sha256_file(path, chunk=16) == hashlib.sha256(payload).hexdigest()

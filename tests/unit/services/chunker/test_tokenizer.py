"""Tokenizer-aware size measurement tests.

Requires network access (or a pre-populated HF cache) on first use to fetch
the small tokenizer files; skips cleanly if unavailable, matching the
project's existing `requires_docling_models`/`requires_rapidocr` pattern.
"""

from __future__ import annotations

import pytest

from engineering_rag.services.chunker.config import TokenizerOptions
from engineering_rag.services.chunker.tokenizer import ChunkTokenizer, get_tokenizer

pytestmark = pytest.mark.integration


def _tokenizer_available() -> bool:
    try:
        get_tokenizer(TokenizerOptions())
    except Exception:  # noqa: BLE001
        return False
    return True


requires_tokenizer = pytest.mark.skipif(
    not _tokenizer_available(), reason="chunker tokenizer not cached/reachable in this environment"
)


@requires_tokenizer
class TestChunkTokenizer:
    def test_counts_tokens(self) -> None:
        tok = ChunkTokenizer("sentence-transformers/all-MiniLM-L6-v2")
        assert tok.count("Transmitter FT-101 provides a 4-20 mA signal.") > 0

    def test_empty_text_is_zero_tokens(self) -> None:
        tok = ChunkTokenizer("sentence-transformers/all-MiniLM-L6-v2")
        assert tok.count("") == 0

    def test_longer_text_has_more_tokens(self) -> None:
        tok = ChunkTokenizer("sentence-transformers/all-MiniLM-L6-v2")
        short = tok.count("Short text.")
        long_ = tok.count("Short text. " * 20)
        assert long_ > short

    def test_length_function_matches_count(self) -> None:
        tok = ChunkTokenizer("sentence-transformers/all-MiniLM-L6-v2")
        fn = tok.length_function()
        assert fn("hello world") == tok.count("hello world")

    def test_get_tokenizer_is_cached(self) -> None:
        a = get_tokenizer(TokenizerOptions())
        b = get_tokenizer(TokenizerOptions())
        assert a is b

    def test_unknown_model_raises_actionable_error(self) -> None:
        with pytest.raises((RuntimeError, OSError)):
            ChunkTokenizer("this-model-definitely-does-not-exist/xyz-12345")

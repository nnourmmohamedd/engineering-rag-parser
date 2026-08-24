"""Controlled recursive splitting tests: conditional, tokenizer-aware, overlapping."""

from __future__ import annotations

import pytest

from engineering_rag.services.chunker.config import ChunkerConfig
from engineering_rag.services.chunker.internal import WorkingChunk
from engineering_rag.services.chunker.models import ContentType, SplitMethod
from engineering_rag.services.chunker.recursive import split_oversized_text_chunk
from engineering_rag.services.chunker.tokenizer import get_tokenizer

from .test_tokenizer import requires_tokenizer

pytestmark = [pytest.mark.integration, requires_tokenizer]


def _text_chunk(text: str) -> WorkingChunk:
    return WorkingChunk(text=text, content_type=ContentType.TEXT, heading_path=["A", "B"], section_title="B")


class TestControlledRecursiveSplitting:
    def test_fitting_chunk_is_not_split(self) -> None:
        config = ChunkerConfig()
        tokenizer = get_tokenizer(config.tokenizer)
        chunk = _text_chunk("A short sentence that easily fits.")
        result = split_oversized_text_chunk(chunk, config=config, tokenizer=tokenizer)
        assert len(result) == 1
        assert result[0] is chunk
        assert result[0].split_method is SplitMethod.HIERARCHICAL
        assert result[0].was_recursively_split is False

    def test_oversized_chunk_is_split_into_multiple_children(self) -> None:
        config = ChunkerConfig(max_tokens=60, target_tokens=40, min_chunk_tokens=10, text_overlap_tokens=5)
        tokenizer = get_tokenizer(config.tokenizer)
        long_text = "This is one sentence about instrumentation engineering. " * 30
        chunk = _text_chunk(long_text)
        result = split_oversized_text_chunk(chunk, config=config, tokenizer=tokenizer)
        assert len(result) > 1
        assert all(c.split_method is SplitMethod.RECURSIVE_TEXT for c in result)
        assert all(c.was_recursively_split for c in result)

    def test_children_stay_within_max_tokens_or_are_flagged(self) -> None:
        config = ChunkerConfig(max_tokens=60, target_tokens=40, min_chunk_tokens=10, text_overlap_tokens=5)
        tokenizer = get_tokenizer(config.tokenizer)
        long_text = "This is one sentence about instrumentation engineering. " * 30
        result = split_oversized_text_chunk(_text_chunk(long_text), config=config, tokenizer=tokenizer)
        for c in result:
            assert c.token_count <= config.max_tokens or c.is_atomic_overflow

    def test_children_preserve_heading_path(self) -> None:
        config = ChunkerConfig(max_tokens=60, target_tokens=40, min_chunk_tokens=10, text_overlap_tokens=5)
        tokenizer = get_tokenizer(config.tokenizer)
        long_text = "This is one sentence about instrumentation engineering. " * 30
        result = split_oversized_text_chunk(_text_chunk(long_text), config=config, tokenizer=tokenizer)
        assert all(c.heading_path == ["A", "B"] for c in result)

    def test_overlap_is_recorded_on_non_first_children(self) -> None:
        config = ChunkerConfig(max_tokens=60, target_tokens=40, min_chunk_tokens=10, text_overlap_tokens=5)
        tokenizer = get_tokenizer(config.tokenizer)
        long_text = "This is one sentence about instrumentation engineering. " * 30
        result = split_oversized_text_chunk(_text_chunk(long_text), config=config, tokenizer=tokenizer)
        assert result[0].overlap_tokens_before == 0
        assert all(c.overlap_tokens_before == config.text_overlap_tokens for c in result[1:])

    def test_deterministic_child_ordering(self) -> None:
        config = ChunkerConfig(max_tokens=60, target_tokens=40, min_chunk_tokens=10, text_overlap_tokens=5)
        tokenizer = get_tokenizer(config.tokenizer)
        long_text = "This is one sentence about instrumentation engineering. " * 30
        first = split_oversized_text_chunk(_text_chunk(long_text), config=config, tokenizer=tokenizer)
        second = split_oversized_text_chunk(_text_chunk(long_text), config=config, tokenizer=tokenizer)
        assert [c.text for c in first] == [c.text for c in second]

    def test_text_with_no_paragraph_or_sentence_boundaries_still_splits_on_words(self) -> None:
        """No "\\n\\n", "\\n" or sentence punctuation present: word/space boundaries must engage."""
        config = ChunkerConfig(max_tokens=20, target_tokens=15, min_chunk_tokens=2, text_overlap_tokens=2)
        tokenizer = get_tokenizer(config.tokenizer)
        chunk = _text_chunk(" ".join(f"tag{i}" for i in range(200)))
        result = split_oversized_text_chunk(chunk, config=config, tokenizer=tokenizer)
        assert len(result) > 1
        assert all(c.text for c in result)
        assert all(c.token_count <= config.max_tokens or c.is_atomic_overflow for c in result)
        assert all((not c.is_atomic_overflow) or c.warnings for c in result)
        combined_words = " ".join(c.text for c in result).split()
        assert "tag0" in combined_words
        assert "tag199" in combined_words

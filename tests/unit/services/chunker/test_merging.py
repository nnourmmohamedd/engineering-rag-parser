"""Safe small-sibling merging tests."""

from __future__ import annotations

import pytest

from engineering_rag.services.chunker.config import ChunkerConfig
from engineering_rag.services.chunker.internal import WorkingChunk
from engineering_rag.services.chunker.merging import merge_small_chunks
from engineering_rag.services.chunker.models import ContentType, SplitMethod
from engineering_rag.services.chunker.tokenizer import get_tokenizer

from .test_tokenizer import requires_tokenizer

pytestmark = [pytest.mark.integration, requires_tokenizer]


def _chunk(
    text: str, content_type: ContentType = ContentType.TEXT, heading: tuple[str, ...] = ("A",)
) -> WorkingChunk:
    return WorkingChunk(
        text=text,
        content_type=content_type,
        heading_path=list(heading),
        split_method=SplitMethod.HIERARCHICAL,
    )


class TestSafeSmallChunkMerging:
    def test_two_small_same_section_chunks_merge(self) -> None:
        config = ChunkerConfig(min_chunk_tokens=50, max_tokens=256)
        tokenizer = get_tokenizer(config.tokenizer)
        chunks = [_chunk("Short A."), _chunk("Short B.")]
        for c in chunks:
            c.token_count = tokenizer.count(c.text)
        result = merge_small_chunks(chunks, config=config, tokenizer=tokenizer, document_id="doc")
        assert len(result) == 1
        assert result[0].split_method is SplitMethod.MERGED
        assert "Short A." in result[0].text and "Short B." in result[0].text

    def test_different_heading_paths_are_not_merged(self) -> None:
        config = ChunkerConfig(min_chunk_tokens=50, max_tokens=256)
        tokenizer = get_tokenizer(config.tokenizer)
        chunks = [_chunk("Short A.", heading=("Section 1",)), _chunk("Short B.", heading=("Section 2",))]
        for c in chunks:
            c.token_count = tokenizer.count(c.text)
        result = merge_small_chunks(chunks, config=config, tokenizer=tokenizer, document_id="doc")
        assert len(result) == 2

    def test_tables_are_never_merged(self) -> None:
        config = ChunkerConfig(min_chunk_tokens=200, max_tokens=256)
        tokenizer = get_tokenizer(config.tokenizer)
        chunks = [
            _chunk("Table A.", content_type=ContentType.TABLE),
            _chunk("Table B.", content_type=ContentType.TABLE),
        ]
        for c in chunks:
            c.token_count = tokenizer.count(c.text)
        result = merge_small_chunks(chunks, config=config, tokenizer=tokenizer, document_id="doc")
        assert len(result) == 2

    def test_adequately_sized_chunks_are_not_merged(self) -> None:
        config = ChunkerConfig(min_chunk_tokens=2, max_tokens=256)
        tokenizer = get_tokenizer(config.tokenizer)
        chunks = [
            _chunk("This chunk is already a perfectly adequate size on its own."),
            _chunk("So is this second chunk, adequately sized on its own too."),
        ]
        for c in chunks:
            c.token_count = tokenizer.count(c.text)
        result = merge_small_chunks(chunks, config=config, tokenizer=tokenizer, document_id="doc")
        assert len(result) == 2

    def test_merge_never_exceeds_max_tokens(self) -> None:
        config = ChunkerConfig(min_chunk_tokens=14, max_tokens=15, target_tokens=15, text_overlap_tokens=0)
        tokenizer = get_tokenizer(config.tokenizer)
        chunks = [_chunk("Short A sentence here."), _chunk("Short B sentence here too, a bit longer.")]
        for c in chunks:
            c.token_count = tokenizer.count(c.text)
        result = merge_small_chunks(chunks, config=config, tokenizer=tokenizer, document_id="doc")
        assert all(c.token_count <= config.max_tokens for c in result)

    def test_merging_disabled_by_config_is_a_noop(self) -> None:
        config = ChunkerConfig(min_chunk_tokens=50, max_tokens=256, merge_small_chunks=False)
        tokenizer = get_tokenizer(config.tokenizer)
        chunks = [_chunk("Short A."), _chunk("Short B.")]
        for c in chunks:
            c.token_count = tokenizer.count(c.text)
        result = merge_small_chunks(chunks, config=config, tokenizer=tokenizer, document_id="doc")
        assert len(result) == 2

    def test_merged_records_source_lineage(self) -> None:
        config = ChunkerConfig(min_chunk_tokens=50, max_tokens=256)
        tokenizer = get_tokenizer(config.tokenizer)
        chunks = [_chunk("Short A."), _chunk("Short B.")]
        for c in chunks:
            c.token_count = tokenizer.count(c.text)
        result = merge_small_chunks(chunks, config=config, tokenizer=tokenizer, document_id="doc")
        assert result[0].merged_from_keys is not None
        assert len(result[0].merged_from_keys) == 2

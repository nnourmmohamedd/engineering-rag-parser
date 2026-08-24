"""Type-specific refinement tests: tables, lists, code, equations, figures."""

from __future__ import annotations

import pytest
from docling_core.types.doc import DoclingDocument

from engineering_rag.services.chunker.config import ChunkerConfig
from engineering_rag.services.chunker.hierarchical import build_hierarchical_chunks
from engineering_rag.services.chunker.internal import WorkingChunk
from engineering_rag.services.chunker.models import ContentType, SplitMethod
from engineering_rag.services.chunker.refs import build_ref_index
from engineering_rag.services.chunker.tokenizer import get_tokenizer
from engineering_rag.services.chunker.type_handlers.code import refine_code_chunk
from engineering_rag.services.chunker.type_handlers.equations import refine_equation_chunk
from engineering_rag.services.chunker.type_handlers.figures import build_figure_chunks
from engineering_rag.services.chunker.type_handlers.lists import refine_list_chunk
from engineering_rag.services.chunker.type_handlers.tables import refine_table_chunk

from .test_tokenizer import requires_tokenizer

pytestmark = [pytest.mark.integration, requires_tokenizer]


class TestTableRefinement:
    def test_fitting_table_is_returned_whole(self, sample_document: DoclingDocument) -> None:
        config = ChunkerConfig()
        tokenizer = get_tokenizer(config.tokenizer)
        ref_index = build_ref_index(sample_document)
        chunk = next(
            c for c in build_hierarchical_chunks(sample_document) if c.content_type is ContentType.TABLE
        )
        result = refine_table_chunk(
            chunk, ref_index=ref_index, config=config, tokenizer=tokenizer, validation_report={}
        )
        assert len(result) == 1
        assert result[0].table_metadata is not None

    def test_oversized_table_splits_by_row_group_with_repeated_headers(
        self, oversized_table_document: DoclingDocument
    ) -> None:
        config = ChunkerConfig(
            max_tokens=100, target_tokens=80, min_chunk_tokens=20, repeat_table_headers=True
        )
        tokenizer = get_tokenizer(config.tokenizer)
        ref_index = build_ref_index(oversized_table_document)
        chunk = next(
            c
            for c in build_hierarchical_chunks(oversized_table_document)
            if c.content_type is ContentType.TABLE
        )
        result = refine_table_chunk(
            chunk, ref_index=ref_index, config=config, tokenizer=tokenizer, validation_report={}
        )
        assert len(result) > 1
        for fragment in result:
            assert fragment.table_metadata is not None
            assert fragment.table_metadata.is_fragment
            assert fragment.table_metadata.header_repeated
            assert "Instrument Tag" in fragment.text

    def test_no_row_lost_across_fragments(self, oversized_table_document: DoclingDocument) -> None:
        config = ChunkerConfig(
            max_tokens=100, target_tokens=80, min_chunk_tokens=20, repeat_table_headers=True
        )
        tokenizer = get_tokenizer(config.tokenizer)
        ref_index = build_ref_index(oversized_table_document)
        chunk = next(
            c
            for c in build_hierarchical_chunks(oversized_table_document)
            if c.content_type is ContentType.TABLE
        )
        result = refine_table_chunk(
            chunk, ref_index=ref_index, config=config, tokenizer=tokenizer, validation_report={}
        )
        combined = "\n".join(r.text for r in result)
        for i in range(1, 41):
            assert f"FT-{100 + i}" in combined

    def test_fragments_stay_within_max_tokens_or_are_flagged(
        self, oversized_table_document: DoclingDocument
    ) -> None:
        config = ChunkerConfig(
            max_tokens=100, target_tokens=80, min_chunk_tokens=20, repeat_table_headers=True
        )
        tokenizer = get_tokenizer(config.tokenizer)
        ref_index = build_ref_index(oversized_table_document)
        chunk = next(
            c
            for c in build_hierarchical_chunks(oversized_table_document)
            if c.content_type is ContentType.TABLE
        )
        result = refine_table_chunk(
            chunk, ref_index=ref_index, config=config, tokenizer=tokenizer, validation_report={}
        )
        for fragment in result:
            assert fragment.token_count <= config.max_tokens or fragment.is_atomic_overflow

    def test_no_cell_data_falls_back_to_atomic_overflow(self) -> None:
        from engineering_rag.services.chunker.models import TableFragmentMeta

        config = ChunkerConfig(max_tokens=5, target_tokens=3, min_chunk_tokens=1, text_overlap_tokens=0)
        tokenizer = get_tokenizer(config.tokenizer)
        chunk = WorkingChunk(
            text="Table 1: A very long caption that exceeds the tiny token budget configured here.",
            content_type=ContentType.TABLE,
            source_element_refs=["#/tables/0"],
            split_method=SplitMethod.HIERARCHICAL,
            table_metadata=TableFragmentMeta(num_rows=0, num_cols=0),
        )
        result = refine_table_chunk(
            chunk, ref_index={}, config=config, tokenizer=tokenizer, validation_report={}
        )
        assert len(result) == 1
        assert result[0].is_atomic_overflow


class TestListRefinement:
    def test_fitting_list_returned_whole(self, sample_document: DoclingDocument) -> None:
        config = ChunkerConfig()
        tokenizer = get_tokenizer(config.tokenizer)
        chunk = next(
            c for c in build_hierarchical_chunks(sample_document) if c.content_type is ContentType.LIST
        )
        result = refine_list_chunk(chunk, config=config, tokenizer=tokenizer)
        assert len(result) == 1

    def test_oversized_list_splits_between_items(self, sample_document: DoclingDocument) -> None:
        config = ChunkerConfig(max_tokens=15, target_tokens=10, min_chunk_tokens=1, text_overlap_tokens=0)
        tokenizer = get_tokenizer(config.tokenizer)
        chunk = next(
            c for c in build_hierarchical_chunks(sample_document) if c.content_type is ContentType.LIST
        )
        result = refine_list_chunk(chunk, config=config, tokenizer=tokenizer)
        assert len(result) >= 1
        combined = "\n".join(r.text for r in result)
        assert "First requirement" in combined
        assert "Third requirement" in combined


class TestCodeRefinement:
    def test_fitting_code_returned_whole(self, sample_document: DoclingDocument) -> None:
        config = ChunkerConfig()
        tokenizer = get_tokenizer(config.tokenizer)
        chunk = next(
            c for c in build_hierarchical_chunks(sample_document) if c.content_type is ContentType.CODE
        )
        result = refine_code_chunk(chunk, config=config, tokenizer=tokenizer)
        assert len(result) == 1
        assert "def read_ft101" in result[0].text

    def test_oversized_code_splits_on_lines_only(self) -> None:
        config = ChunkerConfig(max_tokens=10, target_tokens=8, min_chunk_tokens=1, text_overlap_tokens=0)
        tokenizer = get_tokenizer(config.tokenizer)
        code = "\n".join(f"line_{i} = {i}  # a comment about value {i}" for i in range(30))
        chunk = WorkingChunk(text=code, content_type=ContentType.CODE, split_method=SplitMethod.HIERARCHICAL)
        result = refine_code_chunk(chunk, config=config, tokenizer=tokenizer)
        assert len(result) > 1
        for fragment in result:
            for line in fragment.text.split("\n"):
                assert line in code.split("\n")


class TestEquationRefinement:
    def test_equation_is_never_split(self, sample_document: DoclingDocument) -> None:
        config = ChunkerConfig(
            max_tokens=2, target_tokens=1, min_chunk_tokens=0, text_overlap_tokens=0
        )  # deliberately tiny
        tokenizer = get_tokenizer(config.tokenizer)
        chunk = next(
            c for c in build_hierarchical_chunks(sample_document) if c.content_type is ContentType.EQUATION
        )
        result = refine_equation_chunk(chunk, config=config, tokenizer=tokenizer)
        assert len(result) == 1
        assert result[0].text == chunk.text
        assert result[0].is_atomic_overflow


class TestFigureRecovery:
    def test_captionless_figure_is_recovered_and_flagged(self, sample_document: DoclingDocument) -> None:
        config = ChunkerConfig()
        tokenizer = get_tokenizer(config.tokenizer)
        figures = build_figure_chunks(
            sample_document, config=config, tokenizer=tokenizer, validation_report={}
        )
        assert len(figures) == 1
        assert figures[0].content_type is ContentType.FIGURE
        assert figures[0].warnings  # no caption -> flagged for human review

    def test_decorative_pictures_excluded_when_report_available(
        self, sample_document: DoclingDocument
    ) -> None:
        config = ChunkerConfig()
        tokenizer = get_tokenizer(config.tokenizer)
        picture_ref = sample_document.pictures[0].self_ref
        report = {"pictures": [{"self_ref": picture_ref, "classification": "decorative_repeated"}]}
        figures = build_figure_chunks(
            sample_document, config=config, tokenizer=tokenizer, validation_report=report
        )
        assert figures == []

"""Hierarchical chunking and content-type classification tests."""

from __future__ import annotations

from docling_core.types.doc import DoclingDocument

from engineering_rag.services.chunker.hierarchical import build_hierarchical_chunks
from engineering_rag.services.chunker.models import ContentType


class TestHierarchicalChunking:
    def test_classifies_every_content_type(self, sample_document: DoclingDocument) -> None:
        chunks = build_hierarchical_chunks(sample_document)
        types = {c.content_type for c in chunks}
        assert ContentType.TEXT in types
        assert ContentType.TABLE in types
        assert ContentType.LIST in types
        assert ContentType.CODE in types
        assert ContentType.EQUATION in types
        # FIGURE is recovered separately (type_handlers.figures), not here.

    def test_heading_path_is_preserved(self, sample_document: DoclingDocument) -> None:
        chunks = build_hierarchical_chunks(sample_document)
        text_chunk = next(c for c in chunks if c.content_type is ContentType.TEXT)
        assert text_chunk.heading_path == ["Sample Engineering Specification", "1. Overview"]
        assert text_chunk.section_title == "1. Overview"

    def test_nested_heading_path_reaches_subsection(self, sample_document: DoclingDocument) -> None:
        chunks = build_hierarchical_chunks(sample_document)
        list_chunk = next(c for c in chunks if c.content_type is ContentType.LIST)
        assert list_chunk.heading_path[-1] == "2.1 Requirements"

    def test_source_element_refs_are_populated(self, sample_document: DoclingDocument) -> None:
        chunks = build_hierarchical_chunks(sample_document)
        for chunk in chunks:
            assert chunk.source_element_refs

    def test_provenance_page_numbers_populated(self, sample_document: DoclingDocument) -> None:
        chunks = build_hierarchical_chunks(sample_document)
        for chunk in chunks:
            assert chunk.page_numbers
            assert all(p >= 1 for p in chunk.page_numbers)

    def test_unicode_text_survives(self, sample_document: DoclingDocument) -> None:
        chunks = build_hierarchical_chunks(sample_document)
        text = "\n".join(c.text for c in chunks)
        assert "café" in text
        assert "中文测试" in text

    def test_code_chunk_preserves_indentation(self, sample_document: DoclingDocument) -> None:
        chunks = build_hierarchical_chunks(sample_document)
        code_chunk = next(c for c in chunks if c.content_type is ContentType.CODE)
        assert "    return sensor.read" in code_chunk.text

    def test_table_metadata_captures_shape(self, sample_document: DoclingDocument) -> None:
        chunks = build_hierarchical_chunks(sample_document)
        table_chunk = next(c for c in chunks if c.content_type is ContentType.TABLE)
        assert table_chunk.table_metadata is not None
        assert table_chunk.table_metadata.num_rows == 3
        assert table_chunk.table_metadata.num_cols == 2

    def test_no_empty_chunks_produced(self, sample_document: DoclingDocument) -> None:
        chunks = build_hierarchical_chunks(sample_document)
        assert all(c.text.strip() for c in chunks)

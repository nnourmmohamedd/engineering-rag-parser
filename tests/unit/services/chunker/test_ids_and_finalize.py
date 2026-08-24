"""Stable ID generation, navigation links and retrieval_text construction."""

from __future__ import annotations

from engineering_rag.services.chunker.finalize import finalize_chunks
from engineering_rag.services.chunker.ids import chunk_id, document_id
from engineering_rag.services.chunker.internal import WorkingChunk
from engineering_rag.services.chunker.models import ContentType, SplitMethod


class TestStableIds:
    def test_document_id_is_the_source_sha256(self) -> None:
        assert document_id("abc123") == "abc123"

    def test_chunk_id_is_deterministic(self) -> None:
        a = chunk_id(document_id_="doc", chunk_index=0, text="hello")
        b = chunk_id(document_id_="doc", chunk_index=0, text="hello")
        assert a == b

    def test_chunk_id_changes_with_text(self) -> None:
        a = chunk_id(document_id_="doc", chunk_index=0, text="hello")
        b = chunk_id(document_id_="doc", chunk_index=0, text="world")
        assert a != b

    def test_chunk_id_changes_with_index(self) -> None:
        a = chunk_id(document_id_="doc", chunk_index=0, text="hello")
        b = chunk_id(document_id_="doc", chunk_index=1, text="hello")
        assert a != b

    def test_chunk_id_changes_with_document(self) -> None:
        a = chunk_id(document_id_="doc1", chunk_index=0, text="hello")
        b = chunk_id(document_id_="doc2", chunk_index=0, text="hello")
        assert a != b

    def test_no_uuid_randomness(self) -> None:
        """Two independent processes computing the same inputs get the same ID."""
        ids = {chunk_id(document_id_="doc", chunk_index=0, text="stable") for _ in range(5)}
        assert len(ids) == 1


def _working_chunk(text: str) -> WorkingChunk:
    return WorkingChunk(
        text=text,
        content_type=ContentType.TEXT,
        heading_path=["Intro"],
        split_method=SplitMethod.HIERARCHICAL,
        token_count=3,
    )


class TestFinalize:
    def test_navigation_links_form_a_correct_chain(self) -> None:
        chunks = [_working_chunk("a"), _working_chunk("b"), _working_chunk("c")]
        finalized = finalize_chunks(
            chunks,
            document_id="doc",
            source_filename="f.pdf",
            source_sha256="sha",
            tokenizer_name="tok",
            include_heading_context=True,
        )
        assert finalized[0].previous_chunk_id is None
        assert finalized[0].next_chunk_id == finalized[1].chunk_id
        assert finalized[1].previous_chunk_id == finalized[0].chunk_id
        assert finalized[1].next_chunk_id == finalized[2].chunk_id
        assert finalized[2].next_chunk_id is None

    def test_chunk_index_is_sequential(self) -> None:
        chunks = [_working_chunk("a"), _working_chunk("b")]
        finalized = finalize_chunks(
            chunks,
            document_id="doc",
            source_filename="f.pdf",
            source_sha256="sha",
            tokenizer_name="tok",
            include_heading_context=True,
        )
        assert [c.chunk_index for c in finalized] == [0, 1]

    def test_retrieval_text_includes_heading_when_configured(self) -> None:
        chunks = [_working_chunk("Body text.")]
        finalized = finalize_chunks(
            chunks,
            document_id="doc",
            source_filename="f.pdf",
            source_sha256="sha",
            tokenizer_name="tok",
            include_heading_context=True,
        )
        assert "Intro" in finalized[0].retrieval_text
        assert finalized[0].text == "Body text."  # text itself is untouched

    def test_retrieval_text_equals_text_when_context_disabled(self) -> None:
        chunks = [_working_chunk("Body text.")]
        finalized = finalize_chunks(
            chunks,
            document_id="doc",
            source_filename="f.pdf",
            source_sha256="sha",
            tokenizer_name="tok",
            include_heading_context=False,
        )
        assert finalized[0].retrieval_text == "Body text."

    def test_ids_are_unique_across_the_document(self) -> None:
        chunks = [_working_chunk(f"chunk {i}") for i in range(20)]
        finalized = finalize_chunks(
            chunks,
            document_id="doc",
            source_filename="f.pdf",
            source_sha256="sha",
            tokenizer_name="tok",
            include_heading_context=True,
        )
        assert len({c.chunk_id for c in finalized}) == 20

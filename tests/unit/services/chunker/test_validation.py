"""Chunk validation gate tests."""

from __future__ import annotations

import pytest
from docling_core.types.doc import DoclingDocument

from engineering_rag.services.chunker.config import ChunkerConfig
from engineering_rag.services.chunker.finalize import finalize_chunks
from engineering_rag.services.chunker.internal import WorkingChunk
from engineering_rag.services.chunker.models import ContentType, RunStatus, SplitMethod
from engineering_rag.services.chunker.validation import validate_chunks

from .conftest import build_sample_document


def _finalized(texts: list[str], *, document_id: str = "sha") -> list:
    chunks = [
        WorkingChunk(
            text=t, content_type=ContentType.TEXT, token_count=3, split_method=SplitMethod.HIERARCHICAL
        )
        for t in texts
    ]
    return finalize_chunks(
        chunks,
        document_id=document_id,
        source_filename="f.pdf",
        source_sha256=document_id,
        tokenizer_name="tok",
        include_heading_context=True,
    )


@pytest.fixture
def doc() -> DoclingDocument:
    return build_sample_document()


class TestValidationGates:
    def test_valid_chunks_pass(self, doc: DoclingDocument) -> None:
        chunks = _finalized(["a", "b", "c"])
        report = validate_chunks(
            chunks, doc=doc, document_id="sha", source_sha256="sha", config=ChunkerConfig()
        )
        assert report.status is RunStatus.PASS
        assert not report.failed_gates

    def test_empty_chunk_is_a_hard_failure(self, doc: DoclingDocument) -> None:
        chunks = _finalized(["a", "b"])
        chunks[0].text = ""  # simulate a downstream bug producing empty text
        report = validate_chunks(
            chunks, doc=doc, document_id="sha", source_sha256="sha", config=ChunkerConfig()
        )
        assert report.status is RunStatus.FAIL
        assert any(c.check_id == "no_empty_chunks" and not c.passed for c in report.checks)

    def test_duplicate_ids_are_a_hard_failure(self, doc: DoclingDocument) -> None:
        chunks = _finalized(["a", "b"])
        chunks[1].chunk_id = chunks[0].chunk_id
        report = validate_chunks(
            chunks, doc=doc, document_id="sha", source_sha256="sha", config=ChunkerConfig()
        )
        assert report.status is RunStatus.FAIL
        assert any(c.check_id == "no_duplicate_chunk_ids" and not c.passed for c in report.checks)

    def test_recomputed_id_mismatch_is_a_hard_failure(self, doc: DoclingDocument) -> None:
        chunks = _finalized(["a", "b"])
        chunks[0].chunk_id = "chunk_notreallytherightone000"
        report = validate_chunks(
            chunks, doc=doc, document_id="sha", source_sha256="sha", config=ChunkerConfig()
        )
        assert report.status is RunStatus.FAIL
        assert any(c.check_id == "deterministic_ids_recomputable" and not c.passed for c in report.checks)

    def test_unflagged_oversized_chunk_is_a_hard_failure(self, doc: DoclingDocument) -> None:
        chunks = _finalized(["a"])
        chunks[0].token_count = 99999
        chunks[0].is_atomic_overflow = False
        report = validate_chunks(
            chunks, doc=doc, document_id="sha", source_sha256="sha", config=ChunkerConfig()
        )
        assert report.status is RunStatus.FAIL
        assert any(c.check_id == "ordinary_chunks_within_max_tokens" and not c.passed for c in report.checks)

    def test_flagged_atomic_overflow_passes_when_permitted(self, doc: DoclingDocument) -> None:
        chunks = _finalized(["a"])
        chunks[0].token_count = 99999
        chunks[0].is_atomic_overflow = True
        report = validate_chunks(
            chunks,
            doc=doc,
            document_id="sha",
            source_sha256="sha",
            config=ChunkerConfig(allowed_atomic_overflow=True),
        )
        assert not any(
            c.check_id == "ordinary_chunks_within_max_tokens" and not c.passed for c in report.checks
        )
        assert not any(
            c.check_id == "atomic_overflow_requires_permission" and not c.passed for c in report.checks
        )

    def test_flagged_atomic_overflow_fails_when_not_permitted(self, doc: DoclingDocument) -> None:
        chunks = _finalized(["a"])
        chunks[0].token_count = 99999
        chunks[0].is_atomic_overflow = True
        report = validate_chunks(
            chunks,
            doc=doc,
            document_id="sha",
            source_sha256="sha",
            config=ChunkerConfig(allowed_atomic_overflow=False),
        )
        assert report.status is RunStatus.FAIL
        assert any(
            c.check_id == "atomic_overflow_requires_permission" and not c.passed for c in report.checks
        )

    def test_out_of_range_page_number_is_a_hard_failure(self, doc: DoclingDocument) -> None:
        chunks = _finalized(["a"])
        chunks[0].page_numbers = [9999]
        report = validate_chunks(
            chunks, doc=doc, document_id="sha", source_sha256="sha", config=ChunkerConfig()
        )
        assert report.status is RunStatus.FAIL
        assert any(c.check_id == "page_numbers_within_document_range" and not c.passed for c in report.checks)

    def test_source_identity_mismatch_is_a_hard_failure(self, doc: DoclingDocument) -> None:
        chunks = _finalized(["a"])
        chunks[0].source_sha256 = "wrong-sha"
        report = validate_chunks(
            chunks, doc=doc, document_id="sha", source_sha256="sha", config=ChunkerConfig()
        )
        assert report.status is RunStatus.FAIL
        assert any(c.check_id == "source_identity_traceable" and not c.passed for c in report.checks)

    def test_strict_mode_escalates_warnings_to_fail(self, doc: DoclingDocument) -> None:
        chunks = _finalized(["dup text", "dup text"])
        report = validate_chunks(
            chunks, doc=doc, document_id="sha", source_sha256="sha", config=ChunkerConfig(strict=True)
        )
        assert report.status is RunStatus.FAIL

    def test_pass_with_warnings_never_hides_a_failed_gate(self, doc: DoclingDocument) -> None:
        chunks = _finalized(["dup text", "dup text"])  # triggers a WARNING
        chunks[0].text = ""  # also triggers a CRITICAL failure
        report = validate_chunks(
            chunks, doc=doc, document_id="sha", source_sha256="sha", config=ChunkerConfig(strict=False)
        )
        assert report.status is RunStatus.FAIL

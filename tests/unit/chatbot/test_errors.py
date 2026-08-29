"""Exception -> safe API error translation.

The frontend branches on ``code``, never message text, and no internal
detail (traceback, path, module name) may ever reach a client -- see
``chatbot/errors.py`` for the two rules this module enforces.
"""

from __future__ import annotations

from engineering_rag.chatbot.errors import ErrorCode, translate_exception
from engineering_rag.databases.chroma.errors import DuplicateIdConflictError


class TestDuplicateIdConflictTranslation:
    def test_translates_to_vector_indexing_failed_not_internal_error(self) -> None:
        """Regression test: this exception used to have no entry in the translation table and
        fell through to a generic, unhelpful INTERNAL_ERROR -- exactly the failure mode that
        made the real production incident hard to diagnose from the API response alone."""
        exc = DuplicateIdConflictError(
            "id 'chunk_12853b0e951df7d3' already exists in the collection with a different "
            "content hash (existing='b60fe679...', new='4970ca6b...'). Refusing to silently "
            "overwrite; use --rebuild for a destructive replacement."
        )
        translated = translate_exception(exc)
        assert translated.code == ErrorCode.VECTOR_INDEXING_FAILED
        assert translated.code != ErrorCode.INTERNAL_ERROR
        assert translated.http_status == 409

    def test_translated_message_is_safe_no_leaked_internals(self) -> None:
        """The safe message must never repeat the raw exception text -- no chunk id, no raw
        hash value, no "--rebuild" CLI flag reference reaches the client."""
        exc = DuplicateIdConflictError(
            "id 'chunk_12853b0e951df7d3' already exists in the collection with a different "
            "content hash (existing='b60fe679...', new='4970ca6b...'). Refusing to silently "
            "overwrite; use --rebuild for a destructive replacement."
        )
        translated = translate_exception(exc)
        assert "chunk_12853b0e951df7d3" not in translated.message
        assert "--rebuild" not in translated.message
        assert translated.message  # non-empty, actionable


def test_unrecognised_exception_still_falls_back_to_internal_error() -> None:
    """Sanity check that the fallback path itself still works: an exception with no
    translation entry is exactly where INTERNAL_ERROR remains the correct, safe outcome."""
    translated = translate_exception(RuntimeError("some unrelated internal failure"))
    assert translated.code == ErrorCode.INTERNAL_ERROR
    assert "some unrelated internal failure" not in translated.message

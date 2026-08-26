"""Stable error codes and the translation from internal exceptions to safe API errors.

Two rules govern everything here:

1. **Codes are stable and machine-readable.** The frontend branches on
   ``code``, never on message text, so wording can improve without breaking
   the UI.
2. **Messages are safe to display.** No traceback, no filesystem path, no
   internal module name ever reaches a user. :func:`translate_exception` is
   the single choke point that guarantees it -- an unrecognised exception
   becomes a generic ``INTERNAL_ERROR`` rather than leaking ``repr(exc)``.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ChatbotError", "ErrorCode", "TranslatedError", "translate_exception"]


class ErrorCode:
    """Stable machine-readable error codes shared by the API and the worker."""

    # Upload / validation
    UPLOAD_REJECTED = "UPLOAD_REJECTED"
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
    MESSAGE_NOT_FOUND = "MESSAGE_NOT_FOUND"

    # Selection / retrieval scope
    EMPTY_DOCUMENT_SELECTION = "EMPTY_DOCUMENT_SELECTION"
    DOCUMENT_NOT_READY = "DOCUMENT_NOT_READY"
    UNKNOWN_DOCUMENT_SELECTED = "UNKNOWN_DOCUMENT_SELECTED"
    INVALID_RETRIEVAL_MODE = "INVALID_RETRIEVAL_MODE"

    # Ingestion stages
    PARSER_FAILED = "PARSER_FAILED"
    PARSER_VALIDATION_FAILED = "PARSER_VALIDATION_FAILED"
    CHUNKING_FAILED = "CHUNKING_FAILED"
    CHUNK_VALIDATION_FAILED = "CHUNK_VALIDATION_FAILED"
    EMBEDDING_FAILED = "EMBEDDING_FAILED"
    VECTOR_INDEXING_FAILED = "VECTOR_INDEXING_FAILED"
    BM25_INDEXING_FAILED = "BM25_INDEXING_FAILED"
    INDEX_VALIDATION_FAILED = "INDEX_VALIDATION_FAILED"
    INGESTION_CANCELLED = "INGESTION_CANCELLED"
    INGESTION_INTERRUPTED = "INGESTION_INTERRUPTED"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"

    # Answering
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    ANSWER_GENERATION_FAILED = "ANSWER_GENERATION_FAILED"
    GROUNDING_VALIDATION_FAILED = "GROUNDING_VALIDATION_FAILED"

    # Dependencies / infrastructure
    RETRIEVAL_UNAVAILABLE = "RETRIEVAL_UNAVAILABLE"
    CORPUS_INCOMPATIBLE = "CORPUS_INCOMPATIBLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class TranslatedError:
    """An exception rendered as something safe to return over HTTP."""

    code: str
    message: str
    retryable: bool
    http_status: int = 500


class ChatbotError(Exception):
    """An error already carrying a safe code/message, raised by chatbot code itself."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        http_status: int = 400,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.http_status = http_status

    def as_translated(self) -> TranslatedError:
        return TranslatedError(
            code=self.code,
            message=self.message,
            retryable=self.retryable,
            http_status=self.http_status,
        )


#: Exception *class names* mapped to a safe code, message and retryability.
#: Keyed by name rather than by imported class so this module stays free of
#: heavy imports (chromadb, transformers) that would slow API startup.
_TRANSLATIONS: dict[str, tuple[str, str, bool, int]] = {
    "PreflightError": (
        ErrorCode.PARSER_FAILED,
        "The document could not be accepted for parsing (it may be encrypted, corrupt, or "
        "outside the configured page limit).",
        False,
        422,
    ),
    "ConversionFailedError": (
        ErrorCode.PARSER_FAILED,
        "The document could not be converted. It may be malformed or unsupported.",
        True,
        422,
    ),
    "IndexingInputError": (
        ErrorCode.CHUNK_VALIDATION_FAILED,
        "The chunked output was not admissible for indexing.",
        False,
        422,
    ),
    "CollectionNotFoundError": (
        ErrorCode.RETRIEVAL_UNAVAILABLE,
        "The vector database collection is not available. Check the system status page.",
        True,
        503,
    ),
    "EmptyCollectionError": (
        ErrorCode.RETRIEVAL_UNAVAILABLE,
        "The vector database contains no indexed documents yet.",
        False,
        409,
    ),
    "CorpusCompatibilityError": (
        ErrorCode.CORPUS_INCOMPATIBLE,
        "The vector and lexical indexes describe different document sets. Reprocessing is required "
        "before hybrid retrieval can run.",
        True,
        409,
    ),
    "BM25IndexNotFoundError": (
        ErrorCode.BM25_INDEXING_FAILED,
        "The lexical (BM25) index is missing. It is rebuilt automatically after a successful "
        "ingestion; retry processing a document to rebuild it.",
        True,
        503,
    ),
    "InvalidFilterError": (
        ErrorCode.UNKNOWN_DOCUMENT_SELECTED,
        "The document selection for this query was not valid.",
        False,
        400,
    ),
    "OllamaConnectionError": (
        ErrorCode.LLM_UNAVAILABLE,
        "The local Ollama server is not reachable. Start Ollama and try again.",
        True,
        503,
    ),
    "OllamaTimeoutError": (
        ErrorCode.ANSWER_GENERATION_FAILED,
        "Generating the answer took longer than the configured timeout. Local generation on CPU "
        "can be slow; try a narrower question or a smaller document selection.",
        True,
        504,
    ),
    "OllamaModelNotFoundError": (
        ErrorCode.LLM_UNAVAILABLE,
        "The configured language model is not installed in Ollama.",
        False,
        503,
    ),
    "OllamaError": (
        ErrorCode.LLM_UNAVAILABLE,
        "The local language model returned an error.",
        True,
        503,
    ),
    "TokenizerLoadError": (
        ErrorCode.INTERNAL_ERROR,
        "The tokenizer required for token budgeting could not be loaded.",
        True,
        503,
    ),
    "InvalidStateTransitionError": (
        ErrorCode.INVALID_STATE_TRANSITION,
        "That operation is not valid for this item's current state.",
        False,
        409,
    ),
}


def translate_exception(exc: BaseException) -> TranslatedError:
    """Render ``exc`` as a safe, stable API error.

    A :class:`ChatbotError` already knows its own safe representation. A
    recognised library exception maps through :data:`_TRANSLATIONS`. Anything
    else becomes a generic ``INTERNAL_ERROR`` -- deliberately without the
    original message, because an unrecognised exception is exactly the case
    where a path or internal detail is most likely to leak.
    """
    if isinstance(exc, ChatbotError):
        return exc.as_translated()

    for klass in type(exc).__mro__:
        entry = _TRANSLATIONS.get(klass.__name__)
        if entry is not None:
            code, message, retryable, status = entry
            return TranslatedError(code=code, message=message, retryable=retryable, http_status=status)

    return TranslatedError(
        code=ErrorCode.INTERNAL_ERROR,
        message="An unexpected internal error occurred. Check the application logs for details.",
        retryable=True,
        http_status=500,
    )

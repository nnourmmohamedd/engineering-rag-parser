"""Grounded answer generation: prompt -> abstract LLM client -> parse -> validate -> refuse/answer/repair.

Depends on :mod:`engineering_rag.clients.ollama` (the ``LLMClient``
interface only), :mod:`engineering_rag.prompts.answering`, and
:mod:`engineering_rag.services.grounding`. Never imports ``chromadb``.
"""

from __future__ import annotations

from engineering_rag import __version__

__all__ = [
    "ANSWER_SCHEMA_VERSION",
    "ANSWERER_VERSION",
    "AnswerResponse",
    "AnswerStatus",
    "AnswerTrace",
    "AnswererError",
    "AnsweringConfig",
    "CitationSummary",
    "GroundedAnswerService",
    "LLMAnswerDraft",
    "MalformedModelOutputError",
    "SupportingEvidenceItem",
]

#: Bumped whenever answering semantics change in a way that would alter
#: results for identical input+config.
ANSWERER_VERSION = __version__

from .config import AnsweringConfig  # noqa: E402
from .errors import AnswererError, MalformedModelOutputError  # noqa: E402
from .models import (  # noqa: E402
    ANSWER_SCHEMA_VERSION,
    AnswerResponse,
    AnswerStatus,
    CitationSummary,
    LLMAnswerDraft,
    SupportingEvidenceItem,
)
from .service import AnswerTrace, GroundedAnswerService  # noqa: E402

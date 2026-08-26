"""Deterministic citation and grounding validation.

Depends only on :mod:`engineering_rag.services.context_builder` (its
``ContextPackage`` type) -- never on ``services/answerer`` or
``clients/ollama``, so ``services/answerer`` can depend on this package
without a cycle. See ``README.md`` for exactly what these checks do and do
not prove.
"""

from __future__ import annotations

from engineering_rag import __version__

__all__ = [
    "GROUNDING_SCHEMA_VERSION",
    "GROUNDING_VERSION",
    "CitationCheckResult",
    "GroundingConfig",
    "GroundingError",
    "GroundingReport",
    "GroundingStatus",
    "QuoteCheckResult",
    "normalize_quote_text",
    "validate_grounding",
]

#: Bumped whenever validation semantics change in a way that would alter the
#: status/checks for identical input+config.
GROUNDING_VERSION = __version__

from .config import GroundingConfig  # noqa: E402
from .errors import GroundingError  # noqa: E402
from .models import (  # noqa: E402
    GROUNDING_SCHEMA_VERSION,
    CitationCheckResult,
    GroundingReport,
    GroundingStatus,
    QuoteCheckResult,
)
from .validator import normalize_quote_text, validate_grounding  # noqa: E402

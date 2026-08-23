"""Engineering-grade, local-first PDF parsing package built on Docling.

Public surface is intentionally small: callers build a :class:`ParserConfig`,
then call :func:`engineering_rag_parser.parser.parse_document`. Everything
Docling-specific is confined to :mod:`engineering_rag_parser.pipeline_factory`
so that upstream API churn touches exactly one module.
"""

from __future__ import annotations

__all__ = ["__version__", "PARSER_VERSION"]

# Bumped whenever parsing/normalisation/validation semantics change in a way
# that would alter artifacts for an identical input+config. Recorded in every
# run manifest so downstream stages can detect stale artifacts.
__version__ = "1.0.0"
PARSER_VERSION = __version__

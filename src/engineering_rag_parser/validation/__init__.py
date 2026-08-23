"""Validation framework: coverage, structure, Markdown/JSON QA, visual review.

Validation is a first-class product feature here, not a post-hoc score. Each
sub-module produces :class:`~engineering_rag_parser.domain.CheckResult` records
carrying their own severity, evidence, threshold and remediation, and
:mod:`engineering_rag_parser.validation.report` aggregates them into a single
``PASS`` / ``PASS_WITH_WARNINGS`` / ``FAIL`` verdict.
"""

from __future__ import annotations

__all__ = ["coverage", "markdown", "report", "structure", "visual"]

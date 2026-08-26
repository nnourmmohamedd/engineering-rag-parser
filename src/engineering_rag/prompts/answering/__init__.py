"""Versioned prompt contract for grounded answer generation.

Public surface: :func:`get_prompt_contract` (system prompt + JSON Schema) and
:func:`format_evidence_block` (sanitized ``<SOURCE>`` rendering). No network
calls; no dependency on ``clients/ollama`` or ``services/answerer``.
"""

from __future__ import annotations

__all__ = [
    "LATEST_PROMPT_VERSION",
    "PromptContract",
    "format_evidence_block",
    "get_prompt_contract",
    "sanitize_evidence_text",
]

from .contract import LATEST_PROMPT_VERSION, PromptContract, get_prompt_contract  # noqa: E402
from .evidence_formatting import format_evidence_block, sanitize_evidence_text  # noqa: E402

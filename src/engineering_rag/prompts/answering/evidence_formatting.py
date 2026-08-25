"""Deterministic, escaped formatting of selected evidence into ``<SOURCE>`` blocks.

Retrieved document text is untrusted data (see
``docs/answering/SECURITY_AND_GROUNDING.md``). Delimiting it with an
XML-like tag is necessary but not sufficient on its own — this module also
neutralizes two concrete escape attempts before evidence text is embedded in
the prompt:

1. A literal ``</SOURCE>`` inside document text that could otherwise
   prematurely close the delimiter and make the following text look like it
   is outside any source block.
2. A literal ``[S<n>]``-shaped citation marker inside document text that
   could otherwise be mistaken (by a reader or a confused model) for one of
   the *real*, allow-listed citation markers assigned to actually-selected
   sources.

Neither of these is the security boundary by itself — the system prompt
separately instructs the model to treat source content as data, never
instructions, and :mod:`engineering_rag.services.grounding` separately
verifies, after generation, that every citation used in the final answer is
one of the real IDs handed out for this context package. This module is
defense in depth, not a proof of safety.
"""

from __future__ import annotations

import re

__all__ = ["format_evidence_block", "sanitize_evidence_text"]

_SOURCE_CLOSE_RE = re.compile(r"</SOURCE>", re.IGNORECASE)
_FAKE_CITATION_RE = re.compile(r"\[S(\d+)\]")


def sanitize_evidence_text(text: str) -> str:
    """Neutralize literal closing-tag and citation-marker strings inside untrusted evidence text."""
    without_close_tag = _SOURCE_CLOSE_RE.sub("[literal-text: END SOURCE TAG]", text)
    return _FAKE_CITATION_RE.sub(lambda m: f"[literal-text-not-a-citation:S{m.group(1)}]", without_close_tag)


def format_evidence_block(
    *,
    citation_id: str,
    source_filename: str | None,
    page_numbers: list[int],
    chunk_id: str,
    text: str,
) -> str:
    """Render one selected source as a delimited, sanitized evidence block."""
    pages = ",".join(str(p) for p in page_numbers) if page_numbers else "unknown"
    safe_filename = (source_filename or "unknown").replace('"', "'")
    safe_chunk_id = chunk_id.replace('"', "'")
    safe_text = sanitize_evidence_text(text)
    return (
        f'<SOURCE id="{citation_id}" file="{safe_filename}" pages="{pages}" chunk_id="{safe_chunk_id}">\n'
        f"{safe_text}\n"
        f"</SOURCE>"
    )

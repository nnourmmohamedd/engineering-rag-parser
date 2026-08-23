"""Deterministic text normalisation and tokenisation primitives.

Everything here is pure and side-effect free so it can be unit tested without a
PDF. Two normalisation strengths exist on purpose:

``normalize_for_compare``
    Aggressive. Folds whitespace, ligatures, dash/quote variants and hyphenated
    line breaks so that a page's native text and Docling's text can be compared
    without penalising harmless layout differences.

``critical_tokens``
    Conservative. Extracts numbers, units and acronyms *before* any lossy
    folding, because those are the tokens whose loss actually matters in an
    engineering document (``4-20 mA``, ``FT-101``, ``SIL 2``, ``±0.5%``).

Mixing the two up is the classic way to build a validator that reports 99%
coverage while silently dropping every instrument tag, so the split is enforced
by keeping the aggressive folding out of the token extractor.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence

__all__ = [
    "ACRONYM_RE",
    "NUMBER_RE",
    "char_coverage",
    "critical_tokens",
    "find_duplicated_spans",
    "find_missing_spans",
    "jaccard",
    "normalize_for_compare",
    "normalize_line",
    "sentence_spans",
    "text_sha256",
    "token_recall",
    "word_tokens",
]

# Ligatures Docling/pdfminer may emit differently from the source encoding.
_LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
    "Ĳ": "IJ",
    "ĳ": "ij",
    "Œ": "OE",
    "œ": "oe",
}

# Typographic variants folded to ASCII so they never register as a difference.
_PUNCT_FOLD = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "―": "-",
    "−": "-",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    "​": "",
    "‌": "",
    "‍": "",
    "﻿": "",
    "…": "...",
    "­": "",  # soft hyphen
}

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS_RE = re.compile(r"\s+")

#: pdfminer emits ``(cid:NNN)`` when a glyph has no usable ToUnicode mapping —
#: typically a bullet or a symbol font. It is an artifact of the *extractor*, not
#: content of the document, and leaving it in the baseline would both invent a
#: number token ("127") and report a phantom loss when Docling renders the glyph
#: properly. Removed from both sides of every comparison.
_CID_RE = re.compile(r"\(cid:\d+\)")
# A hyphen at end of line followed by a lowercase continuation = wrapped word.
_HYPHEN_WRAP_RE = re.compile(r"(\w)-\s*\n\s*([a-z])")

_WORD_RE = re.compile(r"[A-Za-z0-9_À-ɏ]+(?:[-'’][A-Za-z0-9_]+)*")

#: Numbers including decimals, percentages and signed values.
#: The lookbehind stops the ``-101`` of ``FT-101`` or the ``5.1`` of ``ISA-5.1``
#: from being harvested as separate "numbers" — those fragments are noise that
#: would inflate the critical-token set and mask a genuine loss.
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9._\-])[+\-±]?\d+(?:[.,]\d+)*\s*(?:%|°[CF]?)?")

#: Acronyms and instrument tags: 2+ capitals, optionally hyphen/digit suffixed
#: (P&ID, PLC, DCS, FT-101, SIL2, 4-20mA style tags, ISA-5.1).
ACRONYM_RE = re.compile(r"\b[A-Z][A-Z&/]{1,}(?:[-_.]?\d+(?:\.\d+)*)?\b")

#: Engineering units worth protecting explicitly.
_UNIT_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*"
    r"(?:mA|mm|cm|m|km|kPa|MPa|Pa|bar|psi|barg|psig|kg|g|t|V|kV|mV|A|kA|W|kW|MW|Hz|kHz|"
    r"%|°C|°F|K|s|ms|min|h|L|mL|m3|in|ft)\b"
)


def normalize_line(text: str) -> str:
    """Fold one line to a stable comparison key.

    Used for repeated-furniture detection, where ``Page 3 of 27`` and
    ``Page 17 of 27`` must collapse to the same key. Digits become ``#`` so
    varying page numbers do not defeat the repetition count.
    """
    s = normalize_for_compare(text)
    s = re.sub(r"\d+", "#", s)
    return s.strip()


def normalize_for_compare(text: str) -> str:
    """Aggressively normalise text for similarity comparison.

    Applies, in order: NFKC folding, ligature expansion, punctuation folding,
    control-character removal, hyphenated-line-break repair, whitespace
    collapsing and case folding.

    This is intentionally lossy. Never feed its output to
    :func:`critical_tokens`.
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = _CID_RE.sub(" ", s)
    for src, dst in _LIGATURES.items():
        s = s.replace(src, dst)
    for src, dst in _PUNCT_FOLD.items():
        s = s.replace(src, dst)
    s = _CONTROL_RE.sub(" ", s)
    s = _HYPHEN_WRAP_RE.sub(r"\1\2", s)
    s = _WS_RE.sub(" ", s)
    return s.strip().casefold()


def text_sha256(text: str) -> str:
    """SHA-256 of the *normalised* text, for cheap page-level change detection."""
    return hashlib.sha256(normalize_for_compare(text).encode("utf-8")).hexdigest()


def word_tokens(text: str) -> list[str]:
    """Word tokens from already-normalised text."""
    return _WORD_RE.findall(text)


def critical_tokens(text: str) -> set[str]:
    """Extract high-information tokens from **raw** (un-folded) text.

    Returns numbers, unit-bearing quantities and acronyms/instrument tags. Case
    is preserved for acronyms because ``PID`` and ``pid`` are different claims
    in an instrumentation document.
    """
    if not text:
        return set()
    # Only the safe part of normalisation: fix ligatures/soft hyphens and
    # collapse whitespace. No case folding, no dash unification, no digit masking.
    s = unicodedata.normalize("NFKC", text)
    s = _CID_RE.sub(" ", s)
    for src, dst in _LIGATURES.items():
        s = s.replace(src, dst)
    s = s.replace("­", "").replace("​", "")
    s = _CONTROL_RE.sub(" ", s)
    s = _HYPHEN_WRAP_RE.sub(r"\1\2", s)
    s = _WS_RE.sub(" ", s)

    tokens: set[str] = set()
    for m in _UNIT_RE.finditer(s):
        tokens.add(_WS_RE.sub("", m.group(0)))
    for m in ACRONYM_RE.finditer(s):
        tok = m.group(0)
        if len(tok) >= 2 and not tok.isdigit():
            tokens.add(tok)
    for m in NUMBER_RE.finditer(s):
        tok = _WS_RE.sub("", m.group(0))
        # Bare single digits are noise (list bullets, page furniture).
        if len(tok.strip("+-±")) >= 2 or tok.endswith("%"):
            tokens.add(tok)
    return tokens


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    """Jaccard similarity of two token sets. Two empty inputs are identical (1.0)."""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    union = sa | sb
    return len(sa & sb) / len(union) if union else 1.0


def token_recall(source: Iterable[str], parsed: Iterable[str]) -> float:
    """Fraction of distinct source tokens that survived into the parsed text.

    Recall — not F1 — because the question a parser must answer is *what did we
    lose*. Extra tokens Docling adds (repaired reading order, table headers)
    are not a defect and must not depress the score.
    """
    ss = set(source)
    if not ss:
        return 1.0
    return len(ss & set(parsed)) / len(ss)


def char_coverage(source_chars: int, parsed_chars: int) -> float:
    """``parsed / source`` clipped to [0, 2]; 1.0 when the source is empty."""
    if source_chars <= 0:
        return 1.0
    return min(parsed_chars / source_chars, 2.0)


def sentence_spans(text: str, min_words: int = 4) -> list[str]:
    """Split normalised text into comparable spans of at least ``min_words`` words.

    Spans, rather than whole pages, let the report point at *which* content went
    missing instead of only reporting that something did.
    """
    if not text:
        return []
    raw = re.split(r"(?<=[.!?;:])\s+|\n+", text)
    out: list[str] = []
    for part in raw:
        part = part.strip()
        if part and len(part.split()) >= min_words:
            out.append(part)
    return out


def find_missing_spans(
    source_text: str, parsed_text: str, *, min_words: int = 6, limit: int = 10
) -> list[str]:
    """Source spans whose content is largely absent from the parsed text.

    A span counts as present when at least 80% of its word types appear in the
    parsed page. That tolerance absorbs reading-order repair and de-hyphenation
    while still catching a genuinely dropped paragraph.
    """
    parsed_norm = normalize_for_compare(parsed_text)
    parsed_words = set(word_tokens(parsed_norm))
    missing: list[str] = []
    for span in sentence_spans(normalize_for_compare(source_text), min_words=min_words):
        words = set(word_tokens(span))
        if not words:
            continue
        if len(words & parsed_words) / len(words) < 0.8:
            missing.append(span)
            if len(missing) >= limit:
                break
    return missing


def find_duplicated_spans(parsed_text: str, *, min_words: int = 6, limit: int = 10) -> list[str]:
    """Spans that appear more than once in the parsed text.

    Duplication is the signature failure of blindly merging an OCR pass into a
    document that already had good embedded text, so it is checked explicitly.
    """
    spans = sentence_spans(normalize_for_compare(parsed_text), min_words=min_words)
    counts = Counter(spans)
    return [span for span, n in counts.items() if n > 1][:limit]


def redact(text: str, max_chars: int, enabled: bool = True) -> str:
    """Truncate text destined for a log or report.

    The source document may be confidential, so no code path should ever write
    its full text into an artifact that is easier to leak than the PDF itself.
    """
    if not enabled:
        return text
    flat = _WS_RE.sub(" ", text).strip()
    if len(flat) <= max_chars:
        return flat
    return flat[:max_chars].rstrip() + "…"


def dedupe_preserving_order(items: Sequence[str]) -> list[str]:
    """De-duplicate while keeping first-seen order (stable, unlike ``set``)."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out

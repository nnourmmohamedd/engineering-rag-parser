"""Deterministic, engineering-aware BM25 tokenizer.

The default tokenizer bm25s ships (``bm25s.tokenize``) uses an English word
regex (``\\b\\w\\w+\\b``) plus stopword removal and no stemming by default.
That default silently destroys the identifiers this corpus depends on:

- ``P&ID`` -> split on ``&`` into ``P`` / ``ID``, both length-1/2 fragments
  the default word-boundary regex drops or mangles.
- ``PT-101`` / ``FT_203`` -> split on ``-``/``_`` into ``PT`` and ``101``,
  losing the tag-number pairing that makes the identifier meaningful.
- ``4-20 mA`` -> split into ``4``, ``20``, ``mA``, losing the range.
- ``IEC 61511`` / ``SIL 2`` / ``ISA-5.1`` -> standard-plus-number pairs that
  must survive as searchable units.
- ``C&I`` -> another ampersand-joined acronym.

This module keeps the alphanumeric-with-internal-hyphen/underscore/ampersand
identifier as one token *in addition to* emitting its plain lowercase form,
so both "PT-101" and "pt 101"-style queries can match. No stemming (BM25
identifier matching on unmodified technical terms is more reliable than a
stemmer's guess), and no stopword removal (a removed "not" or "no" silently
inverts a technical requirement's meaning).
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["TOKENIZER_VERSION", "tokenize", "tokenize_corpus"]

#: Bumped whenever tokenization rules change in a way that would alter which
#: documents a query matches. Recorded in every BM25 index manifest.
TOKENIZER_VERSION = "1.0.0"

# One "word" is a maximal run of alphanumerics plus the internal
# joiners `-`, `_`, `&`, `.`, `/` that engineering identifiers use
# (PT-101, FT_203, P&ID, ISA-5.1, 4-20, C&I) — but a joiner must be
# *between* two alphanumeric characters, so leading/trailing punctuation
# (commas, parentheses, sentence-final periods) is never captured.
_TOKEN_PATTERN = re.compile(r"[0-9A-Za-z]+(?:[-_&./][0-9A-Za-z]+)*", re.UNICODE)


def _normalize_unicode(text: str) -> str:
    """NFKC-normalize so visually-identical Unicode variants tokenize identically."""
    return unicodedata.normalize("NFKC", text)


def tokenize(text: str) -> list[str]:
    """Tokenize one string into a deterministic, lowercase token list.

    Rules (documented, not incidental):

    - Unicode NFKC normalization first, so composed/decomposed variants of
      the same character never silently diverge.
    - Case-folded to lowercase (``casefold`` is used, not ``lower``, for
      correct Unicode case-insensitive matching).
    - A token is a maximal alphanumeric run optionally joined internally by
      ``- _ & . /`` (e.g. ``pt-101``, ``p&id``, ``isa-5.1``, ``4-20``,
      ``iec/61511``). Leading/trailing punctuation is stripped by the regex
      itself (it never matches a joiner at the start/end of a run).
    - A joined identifier is emitted twice: once as the full joined form and
      once with the joiners split into separate sub-tokens (e.g. ``pt-101``
      also yields ``pt`` and ``101``) — this lets a query for "PT 101"
      (space-separated) or "PT-101" (hyphenated) both match the same
      document without requiring exact punctuation agreement, while the
      joined form still lets an exact-identifier query rank higher (it
      matches on both the split terms and the compound token).
    - No stopword removal: dropping "no"/"not"/"never" from a technical
      requirement can invert its meaning, and BM25's own IDF weighting
      already suppresses uninformative high-frequency terms.
    - No stemming: there is no evidence in this domain that conflating
      "valve"/"valves" or "instrument"/"instrumentation" improves ranking,
      and stemming technical identifiers (e.g. "SIL" -> "sil") risks
      merging unrelated terms.
    """
    if not text:
        return []
    normalized = _normalize_unicode(text).casefold()
    tokens: list[str] = []
    for match in _TOKEN_PATTERN.finditer(normalized):
        whole = match.group(0)
        tokens.append(whole)
        if any(sep in whole for sep in "-_&./"):
            parts = [p for p in re.split(r"[-_&./]", whole) if p]
            tokens.extend(p for p in parts if p != whole)
    return tokens


def tokenize_corpus(texts: list[str]) -> list[list[str]]:
    """Tokenize a list of documents, preserving input order exactly."""
    return [tokenize(t) for t in texts]

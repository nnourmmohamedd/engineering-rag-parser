"""Deterministic post-generation citation and grounding validation.

Takes plain, already-parsed fields (never the LLM client, never a network
call) plus the same :class:`~engineering_rag.services.context_builder.models.ContextPackage`
the answer was generated from, and produces a :class:`~.models.GroundingReport`.
Deliberately does not import :mod:`engineering_rag.services.answerer` --
``services/answerer`` depends on ``services/grounding``, never the reverse.

These checks confirm citation structure (every citation used is one of the
real, allow-listed IDs handed to the model) and extractive evidence presence
(a supporting quote actually occurs in its cited source, after documented
normalization). They do **not** mathematically prove that the answer's claim
is semantically entailed by the quote, and a ``PASS`` result is never
"proof of no hallucination" -- see
``docs/answering/SECURITY_AND_GROUNDING.md``.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from engineering_rag.services.context_builder.models import ContextPackage

from .config import GroundingConfig
from .models import CitationCheckResult, GroundingReport, GroundingStatus, QuoteCheckResult

__all__ = ["normalize_quote_text", "validate_grounding"]

_INLINE_CITATION_RE = re.compile(r"\[S(\d+)\]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_WHITESPACE_RE = re.compile(r"\s+")

#: Smart quotes / dashes normalized to their plain-ASCII equivalents before
#: substring comparison, so a model transcribing "smart" punctuation from a
#: source is not falsely flagged as a quote mismatch.
_PUNCT_NORMALIZE = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
    }
)


def normalize_quote_text(text: str) -> str:
    """Documented, deterministic normalization for extractive quote matching.

    Applies: Unicode NFKC normalization, smart-quote/dash folding, whitespace
    collapsing, and casefolding. This is a safety-margin normalization, not a
    semantic one -- it never rewords or truncates the text.
    """
    normalized = unicodedata.normalize("NFKC", text).translate(_PUNCT_NORMALIZE)
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
    return normalized.casefold()


def _extract_inline_citations(answer: str) -> list[str]:
    return [f"S{m}" for m in _INLINE_CITATION_RE.findall(answer)]


def _qualifying_sentences(answer: str) -> list[str]:
    """Heuristic: a sentence "qualifies" as a technical/factual claim if it is non-trivially
    long or contains a digit -- not a proof of semantic content, only a coverage signal.
    """
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(answer) if s.strip()]
    return [s for s in sentences if len(s) >= 40 or any(ch.isdigit() for ch in s)]


def validate_grounding(
    *,
    answer: str,
    insufficient_evidence: bool,
    citations_used: list[str],
    supporting_evidence: list[tuple[str, str]],
    context: ContextPackage,
    config: GroundingConfig,
) -> GroundingReport:
    """Validate one already-parsed model answer against its own context package."""
    valid_ids = {s.citation_id for s in context.selected_sources}
    sources_by_id = {s.citation_id: s for s in context.selected_sources}

    inline_citations = _extract_inline_citations(answer)
    inline_set = set(inline_citations)
    all_seen_ids = inline_set | set(citations_used) | {cid for cid, _ in supporting_evidence}

    citation_checks = [
        CitationCheckResult(
            citation_id=cid,
            valid=cid in valid_ids,
            found_inline=cid in inline_set,
            found_in_citations_used=cid in citations_used,
            reason="" if cid in valid_ids else "not a real citation ID handed out for this context package",
        )
        for cid in sorted(all_seen_ids)
    ]
    unknown_citations = sorted(cid for cid in all_seen_ids if cid not in valid_ids)
    duplicate_citations = sorted(cid for cid, count in Counter(citations_used).items() if count > 1)

    quote_checks: list[QuoteCheckResult] = []
    for cid, quote in supporting_evidence:
        source = sources_by_id.get(cid)
        if source is None:
            quote_checks.append(
                QuoteCheckResult(
                    citation_id=cid,
                    supporting_quote=quote,
                    citation_is_valid=False,
                    found_exact=False,
                    found_normalized=False,
                    reason="citation_id is not in the ContextPackage",
                )
            )
            continue
        found_exact = quote in source.retrieval_text
        found_normalized = normalize_quote_text(quote) in normalize_quote_text(source.retrieval_text)
        quote_checks.append(
            QuoteCheckResult(
                citation_id=cid,
                supporting_quote=quote,
                citation_is_valid=True,
                found_exact=found_exact,
                found_normalized=found_normalized,
                reason="" if found_normalized else "quote not found in cited source text after normalization",
            )
        )

    checks_passed: list[str] = []
    checks_failed: list[str] = []
    warnings: list[str] = []

    if config.fail_on_unknown_citation and unknown_citations:
        checks_failed.append("unknown_citation")
    elif all_seen_ids:
        checks_passed.append("no_unknown_citations")

    mismatched_quotes = [q for q in quote_checks if q.citation_is_valid and not q.found_normalized]
    if config.fail_on_quote_mismatch and mismatched_quotes:
        checks_failed.append("supporting_quote_mismatch")
    elif quote_checks:
        checks_passed.append("supporting_quotes_verified")

    if insufficient_evidence:
        if inline_set or citations_used:
            warnings.append(
                "answer declares insufficient_evidence but also carries citations "
                f"(inline={sorted(inline_set)}, citations_used={citations_used})"
            )
    else:
        distinct_valid_used = {cid for cid in citations_used if cid in valid_ids}
        if config.require_inline_citations and not inline_set:
            checks_failed.append("missing_inline_citation")
        else:
            checks_passed.append("has_inline_citation")

        if len(distinct_valid_used) < config.minimum_citations_for_answer:
            checks_failed.append("insufficient_citation_count")
        else:
            checks_passed.append("citation_count_sufficient")

        if config.require_supporting_quotes:
            quoted_ids = {cid for cid, _ in supporting_evidence}
            missing_quotes = [cid for cid in citations_used if cid in valid_ids and cid not in quoted_ids]
            if missing_quotes:
                checks_failed.append("missing_supporting_quote")
            else:
                checks_passed.append("every_citation_has_a_quote")

    coverage_ratio: float | None = None
    if not insufficient_evidence:
        qualifying = _qualifying_sentences(answer)
        if qualifying:
            with_citation = sum(1 for s in qualifying if _INLINE_CITATION_RE.search(s))
            coverage_ratio = with_citation / len(qualifying)
            if coverage_ratio < config.citation_coverage_warn_below:
                warnings.append(
                    f"citation coverage heuristic {coverage_ratio:.2f} is below "
                    f"{config.citation_coverage_warn_below:.2f} ({with_citation}/{len(qualifying)} "
                    "qualifying sentences carry an inline citation)"
                )

    status: GroundingStatus = "FAIL" if checks_failed else ("PASS_WITH_WARNINGS" if warnings else "PASS")

    return GroundingReport(
        status=status,
        citation_checks=citation_checks,
        quote_checks=quote_checks,
        unknown_citations=unknown_citations,
        duplicate_citations=duplicate_citations,
        citation_coverage_ratio=coverage_ratio,
        checks_passed=checks_passed,
        checks_failed=checks_failed,
        warnings=warnings,
    )

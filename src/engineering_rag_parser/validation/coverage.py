"""Page-level text coverage: native PDF text versus Docling text.

Why several metrics instead of one ratio
----------------------------------------
A single global character ratio is easy to satisfy and easy to be misled by:

* Header/footer removal and reading-order repair legitimately change character
  counts in both directions.
* An image-heavy page can score 1.00 while conveying almost nothing, because
  both sides agree there is little text.
* A page can keep 97% of its characters and still have lost every instrument
  tag, which is the only part an engineer needed.

So each page is scored on character coverage, token Jaccard, token **recall**,
and a separate **critical-token recall** over numbers, units and acronyms, and
low scores are surfaced per page rather than averaged away.
"""

from __future__ import annotations

import logging

from ..config import ParserConfig
from ..domain import CheckResult, PageCoverage, Severity, SourceManifest
from ..normalization import (
    char_coverage,
    critical_tokens,
    find_duplicated_spans,
    find_missing_spans,
    jaccard,
    normalize_for_compare,
    normalize_line,
    redact,
    token_recall,
    word_tokens,
)

__all__ = [
    "build_page_coverage",
    "coverage_checks",
    "document_completeness_check",
    "strip_furniture",
]

logger = logging.getLogger(__name__)


def _furniture_keys(manifest: SourceManifest) -> set[str]:
    """Normalised keys of lines preflight proved to be header/footer furniture."""
    return {
        c.normalized
        for c in manifest.furniture_candidates
        if c.band in {"header", "footer"} and not c.normalized.startswith("image:")
    }


def strip_furniture(text: str, furniture_keys: set[str]) -> tuple[str, int]:
    """Remove proven furniture lines from a page's native text.

    Returns ``(kept_text, characters_removed)``.

    This exists because the canonical body deliberately excludes page headers and
    footers. Comparing that body against a native baseline that still contains
    ``www.example.com   Page 16 of 27`` is not a fair test: it reports the page's
    own page number as "lost content" and fails every page in the document. Both
    sides must have the same furniture removed.
    """
    if not furniture_keys:
        return text, 0
    kept: list[str] = []
    removed = 0
    for line in text.splitlines():
        if line.strip() and normalize_line(line) in furniture_keys:
            removed += len(line)
            continue
        kept.append(line)
    return "\n".join(kept), removed


def build_page_coverage(
    manifest: SourceManifest,
    native_texts: dict[int, str],
    parsed_texts: dict[int, str],
    config: ParserConfig,
) -> list[PageCoverage]:
    """Compare each source page against Docling's text for that page.

    The native baseline has proven header/footer furniture removed first, so that
    both sides of the comparison represent *body* content.
    """
    thresholds = config.thresholds
    source_pages = {p.page_no: p for p in manifest.pages}
    furniture_keys = _furniture_keys(manifest)
    rows: list[PageCoverage] = []

    for page_no in sorted(source_pages):
        src_page = source_pages[page_no]
        native_raw = native_texts.get(page_no, "")
        native, furniture_removed = strip_furniture(native_raw, furniture_keys)
        parsed = parsed_texts.get(page_no, "")

        native_norm = normalize_for_compare(native)
        parsed_norm = normalize_for_compare(parsed)
        native_words = word_tokens(native_norm)
        parsed_words = word_tokens(parsed_norm)

        # Content that spans a page break is attributed by Docling to the page
        # where the paragraph STARTS. Comparing a page in isolation therefore
        # reports correct reading-order repair as loss. Neighbouring pages are
        # consulted to separate *relocated* content from *lost* content.
        neighbours = "\n".join(
            parsed_texts.get(adjacent, "")
            for adjacent in (page_no - 1, page_no + 1)
            if adjacent in parsed_texts
        )
        src_crit = critical_tokens(native)
        parsed_crit = critical_tokens(parsed)
        neighbour_crit = critical_tokens(neighbours)
        absent_here = src_crit - parsed_crit
        relocated_crit = sorted(absent_here & neighbour_crit)
        missing_crit = sorted(absent_here - neighbour_crit)

        row = PageCoverage(
            page_no=page_no,
            source_chars=len(native_norm),
            parsed_chars=len(parsed_norm),
            source_words=len(native_words),
            parsed_words=len(parsed_words),
            furniture_chars_excluded=furniture_removed,
            source_chars_with_furniture=len(normalize_for_compare(native_raw)),
            char_coverage=round(char_coverage(len(native_norm), len(parsed_norm)), 4),
            token_jaccard=round(jaccard(native_words, parsed_words), 4),
            token_recall=round(token_recall(native_words, parsed_words), 4),
            critical_token_recall=round(token_recall(src_crit, parsed_crit | neighbour_crit), 4),
            missing_critical_tokens=missing_crit[:25],
            relocated_critical_tokens=relocated_crit[:25],
            missing_spans=[
                redact(s, config.text_sample_chars, config.redact_text_samples)
                for s in find_missing_spans(native, parsed + "\n" + neighbours)
            ],
            relocated_spans=[
                redact(s, config.text_sample_chars, config.redact_text_samples)
                for s in find_missing_spans(native, parsed)
                if s not in {m for m in find_missing_spans(native, parsed + "\n" + neighbours)}
            ],
            duplicated_spans=[
                redact(s, config.text_sample_chars, config.redact_text_samples)
                for s in find_duplicated_spans(parsed)
            ],
            is_sparse_text=src_page.is_sparse_text,
            is_image_heavy=src_page.is_image_heavy,
            needs_visual_review=src_page.needs_visual_review,
        )

        notes: list[str] = []
        severity = Severity.INFO

        # An image-heavy or sparse page must never be judged complete on text
        # counts alone — that is exactly how a page of pure diagram passes.
        if row.is_sparse_text:
            notes.append(
                f"Only {src_page.char_count} native characters: text metrics are not evidence of "
                "completeness for this page. Visual review governs."
            )
        if src_page.substantive_image_count:
            notes.append(
                f"{src_page.substantive_image_count} substantive figure(s) present "
                f"({src_page.substantive_image_area_fraction:.0%} of the page): content is visual."
            )

        if row.relocated_spans or row.relocated_critical_tokens:
            notes.append(
                f"{len(row.relocated_spans)} span(s) and {len(row.relocated_critical_tokens)} critical "
                "token(s) appear on an adjacent page: Docling attributes a paragraph crossing a page "
                "break to the page where it starts. Content is retained, page attribution differs."
            )

        # Text-quality thresholds only bite where there is enough text to judge.
        if row.source_chars >= thresholds.sparse_text_char_threshold:
            explained_by_relocation = bool(row.relocated_spans) and not row.missing_spans
            if row.char_coverage < thresholds.page_char_coverage_fail and not explained_by_relocation:
                severity = Severity.CRITICAL
                notes.append(
                    f"Character coverage {row.char_coverage:.0%} is below the FAIL threshold "
                    f"{thresholds.page_char_coverage_fail:.0%}."
                )
            elif row.char_coverage < thresholds.page_char_coverage_warn:
                severity = max(severity, Severity.WARNING, key=_severity_rank)
                notes.append(
                    f"Character coverage {row.char_coverage:.0%} is below the warning threshold "
                    f"{thresholds.page_char_coverage_warn:.0%}."
                )
            if row.token_recall < thresholds.page_token_recall_warn:
                severity = max(severity, Severity.WARNING, key=_severity_rank)
                notes.append(
                    f"Only {row.token_recall:.0%} of source word types survived "
                    f"(warn below {thresholds.page_token_recall_warn:.0%})."
                )
            if row.critical_token_recall < thresholds.critical_token_recall_fail and src_crit:
                severity = Severity.CRITICAL
                notes.append(
                    f"Critical-token recall {row.critical_token_recall:.0%} is below "
                    f"{thresholds.critical_token_recall_fail:.0%}; missing e.g. {missing_crit[:6]}."
                )
        if row.duplicated_spans:
            severity = max(severity, Severity.WARNING, key=_severity_rank)
            notes.append(
                f"{len(row.duplicated_spans)} duplicated span(s) detected — a signature of an OCR pass "
                "merged over existing embedded text."
            )

        row.severity = severity
        row.notes = notes
        rows.append(row)

    return rows


def _severity_rank(severity: Severity) -> int:
    return {Severity.INFO: 0, Severity.WARNING: 1, Severity.CRITICAL: 2}[severity]


def document_completeness_check(
    manifest: SourceManifest,
    native_texts: dict[int, str],
    parsed_texts: dict[int, str],
    config: ParserConfig,
) -> CheckResult:
    """Whole-document comparison — the gate that detects *true* content loss.

    Per-page metrics cannot separate loss from re-attribution: a paragraph that
    crosses a page break legitimately moves. This check ignores page boundaries
    entirely and asks the only question that matters for a gate — is any
    high-information token absent from the **entire** parsed document?
    """
    furniture_keys = _furniture_keys(manifest)
    native_all = "\n".join(
        strip_furniture(native_texts.get(p, ""), furniture_keys)[0] for p in sorted(native_texts)
    )
    parsed_all = "\n".join(parsed_texts.get(p, "") for p in sorted(parsed_texts))

    src_crit = critical_tokens(native_all)
    parsed_crit = critical_tokens(parsed_all)
    missing = sorted(src_crit - parsed_crit)
    recall = token_recall(src_crit, parsed_crit)

    native_words = set(word_tokens(normalize_for_compare(native_all)))
    parsed_words = set(word_tokens(normalize_for_compare(parsed_all)))
    word_recall = token_recall(native_words, parsed_words)
    missing_words = sorted(native_words - parsed_words)

    passed = recall >= config.thresholds.critical_token_recall_fail
    return CheckResult(
        check_id="document_text_completeness",
        title="No high-information token is lost from the document as a whole",
        passed=passed,
        severity=Severity.CRITICAL,
        gate=True,
        summary=(
            f"Document-level critical-token recall {recall:.1%} "
            f"({len(src_crit) - len(missing)}/{len(src_crit)} tokens), word-type recall {word_recall:.1%}."
            + (f" Missing: {missing[:12]}" if missing else " No critical token is missing document-wide.")
        ),
        evidence={
            "critical_tokens_source": len(src_crit),
            "critical_tokens_parsed": len(parsed_crit),
            "critical_token_recall": round(recall, 4),
            "missing_critical_tokens": missing[:40],
            "word_type_recall": round(word_recall, 4),
            "missing_word_types_sample": missing_words[:40],
            "native_chars": len(normalize_for_compare(native_all)),
            "parsed_chars": len(normalize_for_compare(parsed_all)),
        },
        threshold={"critical_token_recall_fail": config.thresholds.critical_token_recall_fail},
        remediation="A token missing here is absent from the whole document, not merely moved between "
        "pages; inspect the corresponding page rendering.",
    )


def coverage_checks(
    pages: list[PageCoverage], manifest: SourceManifest, config: ParserConfig
) -> list[CheckResult]:
    """Aggregate page coverage into gate-level checks."""
    thresholds = config.thresholds
    checks: list[CheckResult] = []

    # --- Page count integrity -------------------------------------------------
    parsed_pages = {p.page_no for p in pages}
    expected = set(range(1, manifest.page_count + 1))
    missing = sorted(expected - parsed_pages)
    checks.append(
        CheckResult(
            check_id="page_count_match",
            title="Every source page is represented in the parsed document",
            passed=not missing,
            severity=Severity.CRITICAL,
            gate=True,
            summary=(
                f"{len(parsed_pages)}/{manifest.page_count} source pages present in the parse."
                if not missing
                else f"Missing pages: {missing}"
            ),
            evidence={"source_page_count": manifest.page_count, "parsed_page_count": len(parsed_pages),
                      "missing_pages": missing},
            threshold={"required": "all source pages"},
            remediation="Investigate the conversion log for page-level failures and re-run.",
        )
    )

    # --- Monotonic, non-duplicated numbering ---------------------------------
    ordered = [p.page_no for p in pages]
    duplicates = sorted({n for n in ordered if ordered.count(n) > 1})
    monotonic = ordered == sorted(ordered)
    checks.append(
        CheckResult(
            check_id="page_numbering_monotonic",
            title="Page numbering is monotonic with no duplicates",
            passed=monotonic and not duplicates,
            severity=Severity.CRITICAL,
            gate=True,
            summary="Page numbers ascend without repetition."
            if monotonic and not duplicates
            else f"monotonic={monotonic}, duplicates={duplicates}",
            evidence={"duplicates": duplicates, "monotonic": monotonic},
            threshold={"required": "strictly ascending, unique"},
            remediation="A duplicated page number indicates the same page was assembled twice.",
        )
    )

    # --- Provenance coverage --------------------------------------------------
    no_prov = [p.page_no for p in pages if not p.has_provenance]
    covered = 1.0 - (len(no_prov) / len(pages)) if pages else 0.0
    checks.append(
        CheckResult(
            check_id="page_provenance_coverage",
            title="Every page carries at least one item with provenance",
            passed=covered >= thresholds.min_pages_with_provenance,
            severity=Severity.CRITICAL,
            gate=True,
            summary=f"{covered:.0%} of pages have provenance-bearing content."
            + (f" Pages without: {no_prov}" if no_prov else ""),
            evidence={"pages_without_provenance": no_prov, "coverage": round(covered, 4)},
            threshold={"min_pages_with_provenance": thresholds.min_pages_with_provenance},
            remediation="Pages with no provenance cannot be cited by a downstream RAG stage; "
            "inspect the page image and confirm whether the page is genuinely blank.",
        )
    )

    # --- Critical token loss --------------------------------------------------
    crit_fail = [p for p in pages if p.missing_critical_tokens]
    checks.append(
        CheckResult(
            check_id="critical_token_recall",
            title="Numbers, units and acronyms survive extraction (page-local)",
            passed=not crit_fail,
            # Page-local attribution is a WARNING; genuine loss is gated by
            # `document_text_completeness`, which ignores page boundaries.
            severity=Severity.WARNING,
            gate=False,
            summary="No page lost critical tokens beyond threshold."
            if not crit_fail
            else f"{len(crit_fail)} page(s) below critical-token threshold: {[p.page_no for p in crit_fail]}",
            evidence={
                "pages": [
                    {"page_no": p.page_no, "recall": p.critical_token_recall,
                     "missing_sample": p.missing_critical_tokens[:10],
                     "relocated_sample": p.relocated_critical_tokens[:10]}
                    for p in crit_fail
                ]
            },
            threshold={"critical_token_recall_fail": thresholds.critical_token_recall_fail},
            remediation="Inspect the page image; a genuine loss of instrument tags or set-points "
            "must be corrected before the document is used for retrieval.",
        )
    )

    # --- Low text coverage (warning tier) ------------------------------------
    judged = [p for p in pages if p.source_chars >= thresholds.sparse_text_char_threshold]
    low = [p for p in judged if p.char_coverage < thresholds.page_char_coverage_warn]
    checks.append(
        CheckResult(
            check_id="page_text_coverage",
            title="Text-bearing pages retain their characters",
            passed=not low,
            severity=Severity.WARNING,
            gate=False,
            summary=f"{len(judged) - len(low)}/{len(judged)} text-bearing pages meet the coverage threshold."
            + (f" Below threshold: {[p.page_no for p in low]}" if low else ""),
            evidence={
                "pages": [
                    {"page_no": p.page_no, "char_coverage": p.char_coverage,
                     "token_recall": p.token_recall, "source_chars": p.source_chars}
                    for p in low
                ],
                "excluded_sparse_pages": [
                    p.page_no for p in pages if p.source_chars < thresholds.sparse_text_char_threshold
                ],
            },
            threshold={"page_char_coverage_warn": thresholds.page_char_coverage_warn,
                       "applies_when_source_chars_gte": thresholds.sparse_text_char_threshold},
            remediation="Compare the page image with the Markdown; header/footer removal explains small "
            "deficits, a missing paragraph does not.",
        )
    )

    # --- Duplicated spans -----------------------------------------------------
    dup = [p for p in pages if p.duplicated_spans]
    checks.append(
        CheckResult(
            check_id="no_duplicated_spans",
            title="No page repeats the same span of text",
            passed=not dup,
            severity=Severity.WARNING,
            gate=False,
            summary="No duplicated spans detected."
            if not dup
            else f"{len(dup)} page(s) contain duplicated spans: {[p.page_no for p in dup]}",
            evidence={"pages": [{"page_no": p.page_no, "spans": p.duplicated_spans[:3]} for p in dup]},
            threshold={"rule": "a normalised span of >= 6 words must not occur twice on a page"},
            remediation="Duplication usually means an OCR pass was merged over embedded text; "
            "disable OCR for digitally generated PDFs.",
        )
    )

    return checks

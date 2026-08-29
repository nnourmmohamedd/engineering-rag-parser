from __future__ import annotations

from engineering_rag.services.context_builder.models import ContextPackage, SelectedSource
from engineering_rag.services.grounding import GroundingConfig, validate_grounding


def _source(citation_id: str, text: str) -> SelectedSource:
    return SelectedSource(
        citation_id=citation_id,
        chunk_id=f"chunk-{citation_id}",
        retrieval_text=text,
        selection_order=1,
        token_count=10,
    )


def _package(*sources: SelectedSource) -> ContextPackage:
    return ContextPackage(
        query="q",
        query_hash="h",
        retrieval_mode="vector",
        selected_sources=list(sources),
        context_token_count=10,
        token_budget=5000,
        reserved_output_tokens=1024,
        prompt_overhead_tokens=1300,
        context_text="",
    )


class TestValidCitations:
    def test_all_citations_valid_passes(self) -> None:
        context = _package(_source("S1", "FEED develops the control philosophy."))
        report = validate_grounding(
            answer="FEED develops the control philosophy [S1].",
            insufficient_evidence=False,
            citations_used=["S1"],
            supporting_evidence=[("S1", "FEED develops the control philosophy")],
            context=context,
            config=GroundingConfig(),
        )
        assert report.status == "PASS"
        assert report.unknown_citations == []

    def test_unknown_citation_fails(self) -> None:
        context = _package(_source("S1", "FEED develops the control philosophy."))
        report = validate_grounding(
            answer="Claim [S1][S2].",
            insufficient_evidence=False,
            citations_used=["S1", "S2"],
            supporting_evidence=[("S1", "FEED develops the control philosophy")],
            context=context,
            config=GroundingConfig(),
        )
        assert report.status == "FAIL"
        assert "S2" in report.unknown_citations
        assert "unknown_citation" in report.checks_failed

    def test_unknown_citation_can_be_downgraded_to_non_fatal_via_config(self) -> None:
        context = _package(_source("S1", "Some text."))
        report = validate_grounding(
            answer="Claim [S1][S2].",
            insufficient_evidence=False,
            citations_used=["S1", "S2"],
            supporting_evidence=[("S1", "Some text")],
            context=context,
            config=GroundingConfig(fail_on_unknown_citation=False),
        )
        assert "unknown_citation" not in report.checks_failed

    def test_fake_citation_embedded_in_source_text_cannot_become_valid(self) -> None:
        # The source text itself contains a "[S999]"-shaped string; it must never be treated
        # as a real citation ID just because it appears to match the pattern.
        context = _package(_source("S1", "The document says [S999] is important."))
        report = validate_grounding(
            answer="Per the source [S999].",
            insufficient_evidence=False,
            citations_used=["S999"],
            supporting_evidence=[],
            context=context,
            config=GroundingConfig(),
        )
        assert report.status == "FAIL"
        assert "S999" in report.unknown_citations


class TestQuoteMatching:
    def test_exact_quote_matches(self) -> None:
        context = _package(_source("S1", "Exact phrase here."))
        report = validate_grounding(
            answer="Claim [S1].",
            insufficient_evidence=False,
            citations_used=["S1"],
            supporting_evidence=[("S1", "Exact phrase here.")],
            context=context,
            config=GroundingConfig(),
        )
        assert all(q.found_exact for q in report.quote_checks)
        assert report.status == "PASS"

    def test_normalized_quote_matches_smart_quotes_and_whitespace(self) -> None:
        context = _package(_source("S1", "The valve’s   role   is critical."))
        report = validate_grounding(
            answer="Claim [S1].",
            insufficient_evidence=False,
            citations_used=["S1"],
            supporting_evidence=[("S1", "the valve's role is critical")],
            context=context,
            config=GroundingConfig(),
        )
        assert report.quote_checks[0].found_normalized is True
        assert report.status == "PASS"

    def test_fabricated_quote_fails(self) -> None:
        context = _package(_source("S1", "The actual sentence in the document."))
        report = validate_grounding(
            answer="Claim [S1].",
            insufficient_evidence=False,
            citations_used=["S1"],
            supporting_evidence=[("S1", "a sentence that was never in the document")],
            context=context,
            config=GroundingConfig(),
        )
        assert report.status == "FAIL"
        assert "supporting_quote_mismatch" in report.checks_failed

    def test_quote_mismatch_can_be_downgraded_via_config(self) -> None:
        context = _package(_source("S1", "The actual sentence."))
        report = validate_grounding(
            answer="Claim [S1].",
            insufficient_evidence=False,
            citations_used=["S1"],
            supporting_evidence=[("S1", "fabricated text")],
            context=context,
            config=GroundingConfig(fail_on_quote_mismatch=False),
        )
        assert "supporting_quote_mismatch" not in report.checks_failed


class TestAnswerCitationRequirements:
    def test_answer_without_citation_fails(self) -> None:
        context = _package(_source("S1", "Some evidence text."))
        report = validate_grounding(
            answer="A claim with no citation at all.",
            insufficient_evidence=False,
            citations_used=[],
            supporting_evidence=[],
            context=context,
            config=GroundingConfig(),
        )
        assert report.status == "FAIL"
        assert "missing_inline_citation" in report.checks_failed

    def test_refusal_without_citation_passes(self) -> None:
        context = _package(_source("S1", "Unrelated evidence."))
        report = validate_grounding(
            answer="I could not find enough evidence to answer this reliably.",
            insufficient_evidence=True,
            citations_used=[],
            supporting_evidence=[],
            context=context,
            config=GroundingConfig(),
        )
        assert report.status == "PASS"

    def test_refusal_carrying_citations_is_a_warning_not_a_hard_fail(self) -> None:
        context = _package(_source("S1", "Some evidence."))
        report = validate_grounding(
            answer="Insufficient evidence, though [S1] discusses something related.",
            insufficient_evidence=True,
            citations_used=["S1"],
            supporting_evidence=[],
            context=context,
            config=GroundingConfig(),
        )
        assert report.status == "PASS_WITH_WARNINGS"
        assert any("insufficient_evidence" in w for w in report.warnings)


class TestCitationBookkeeping:
    def test_duplicate_citations_normalized(self) -> None:
        context = _package(_source("S1", "text"))
        report = validate_grounding(
            answer="Claim [S1][S1].",
            insufficient_evidence=False,
            citations_used=["S1", "S1"],
            supporting_evidence=[("S1", "text")],
            context=context,
            config=GroundingConfig(),
        )
        assert report.duplicate_citations == ["S1"]

    def test_citation_ordering_is_stable(self) -> None:
        context = _package(_source("S1", "a"), _source("S2", "b"))
        report = validate_grounding(
            answer="Claims [S2][S1].",
            insufficient_evidence=False,
            citations_used=["S2", "S1"],
            supporting_evidence=[("S1", "a"), ("S2", "b")],
            context=context,
            config=GroundingConfig(),
        )
        ids = [c.citation_id for c in report.citation_checks]
        assert ids == sorted(ids)

    def test_citation_coverage_ratio_computed(self) -> None:
        context = _package(_source("S1", "one two three four five six seven eight nine"))
        long_uncited_sentence = "This is a rather long sentence with no citation marker at all here."
        report = validate_grounding(
            answer=f"Cited claim [S1]. {long_uncited_sentence}",
            insufficient_evidence=False,
            citations_used=["S1"],
            supporting_evidence=[("S1", "one two three four five six seven eight nine")],
            context=context,
            config=GroundingConfig(),
        )
        assert report.citation_coverage_ratio is not None
        assert 0.0 <= report.citation_coverage_ratio <= 1.0


class TestStatusLevels:
    def test_pass_with_no_warnings_or_failures(self) -> None:
        context = _package(_source("S1", "clear evidence sentence"))
        report = validate_grounding(
            answer="Claim [S1].",
            insufficient_evidence=False,
            citations_used=["S1"],
            supporting_evidence=[("S1", "clear evidence sentence")],
            context=context,
            config=GroundingConfig(),
        )
        assert report.status == "PASS"

    def test_pass_with_warnings_when_only_soft_signal_present(self) -> None:
        """The coverage-ratio *warning* fires below citation_coverage_warn_below independently
        of the hard uncited-claim gate -- disabled here to isolate the warning path itself
        (see TestCitationCompleteness for the hard-gate behavior, on by default)."""
        context = _package(_source("S1", "one two three four five six seven eight nine ten"))
        long_text = "x" * 60  # qualifies as a technical-length sentence but carries no citation
        report = validate_grounding(
            answer=f"Cited [S1]. {long_text}.",
            insufficient_evidence=False,
            citations_used=["S1"],
            supporting_evidence=[("S1", "one two three four five six seven eight nine ten")],
            context=context,
            config=GroundingConfig(citation_coverage_warn_below=0.99, fail_on_uncited_claim=False),
        )
        assert report.status == "PASS_WITH_WARNINGS"

    def test_fail_status_on_hard_check_failure(self) -> None:
        context = _package(_source("S1", "text"))
        report = validate_grounding(
            answer="Uncited claim.",
            insufficient_evidence=False,
            citations_used=[],
            supporting_evidence=[],
            context=context,
            config=GroundingConfig(),
        )
        assert report.status == "FAIL"


class TestCitationCompleteness:
    """The claim-level coverage gate: every citation-qualifying sentence must carry a
    citation, independent of the answer's total citation count."""

    def test_single_claim_single_citation_is_complete(self) -> None:
        """One passage genuinely is sufficient when the whole answer is that one claim."""
        context = _package(_source("S1", "The mandate of C&I engineering is safety and reliability."))
        report = validate_grounding(
            answer="The mandate of C&I engineering is safety and reliability [S1].",
            insufficient_evidence=False,
            citations_used=["S1"],
            supporting_evidence=[("S1", "The mandate of C&I engineering is safety and reliability")],
            context=context,
            config=GroundingConfig(),
        )
        assert report.status == "PASS"
        assert report.uncited_claims == []
        assert "uncited_factual_claim" not in report.checks_failed

    def test_high_citation_count_does_not_offset_one_uncited_claim(self) -> None:
        """Citation count alone is never completeness: 3 citations elsewhere in the answer
        must not paper over one specific sentence that has none."""
        context = _package(
            _source("S1", "one two three four five six seven eight nine ten"),
            _source("S2", "eleven twelve thirteen fourteen fifteen sixteen seventeen"),
            _source("S3", "eighteen nineteen twenty twentyone twentytwo twentythree"),
        )
        uncited = "y" * 60  # qualifies (length >= 40) but carries no [S<n>] marker
        report = validate_grounding(
            answer=(
                f"First claim, cited [S1]. Second claim, cited [S2]. Third claim also cited [S3]. {uncited}."
            ),
            insufficient_evidence=False,
            citations_used=["S1", "S2", "S3"],
            supporting_evidence=[
                ("S1", "one two three four five six seven eight nine ten"),
                ("S2", "eleven twelve thirteen fourteen fifteen sixteen seventeen"),
                ("S3", "eighteen nineteen twenty twentyone twentytwo twentythree"),
            ],
            context=context,
            config=GroundingConfig(),
        )
        assert report.status == "FAIL"
        assert "uncited_factual_claim" in report.checks_failed
        assert report.uncited_claims == [f"{uncited}."]

    def test_gate_disableable_for_backward_compatible_soft_mode(self) -> None:
        context = _package(_source("S1", "cited text"))
        uncited = "z" * 60
        report = validate_grounding(
            answer=f"Cited claim [S1]. {uncited}.",
            insufficient_evidence=False,
            citations_used=["S1"],
            supporting_evidence=[("S1", "cited text")],
            context=context,
            config=GroundingConfig(fail_on_uncited_claim=False),
        )
        assert report.status == "PASS_WITH_WARNINGS"
        assert report.uncited_claims == [f"{uncited}."]
        assert "uncited_factual_claim" not in report.checks_failed

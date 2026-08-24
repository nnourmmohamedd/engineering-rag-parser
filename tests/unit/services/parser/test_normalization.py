"""Unit tests for the text normalisation and comparison primitives."""

from __future__ import annotations

import pytest

from engineering_rag.services.parser.normalization import (
    char_coverage,
    critical_tokens,
    dedupe_preserving_order,
    find_duplicated_spans,
    find_missing_spans,
    jaccard,
    normalize_for_compare,
    normalize_line,
    redact,
    sentence_spans,
    text_sha256,
    token_recall,
    word_tokens,
)


class TestNormalizeForCompare:
    def test_expands_ligatures(self) -> None:
        assert normalize_for_compare("workﬂow deﬁnition") == "workflow definition"

    def test_repairs_hyphenated_line_break(self) -> None:
        assert normalize_for_compare("instru-\nmentation loop") == "instrumentation loop"

    def test_collapses_whitespace_and_case(self) -> None:
        assert normalize_for_compare("  These   Deliverables \n Define ") == "these deliverables define"

    def test_folds_typographic_punctuation(self) -> None:
        assert normalize_for_compare("“quoted” – dash") == '"quoted" - dash'

    def test_removes_soft_hyphen(self) -> None:
        assert normalize_for_compare("instru­mentation") == "instrumentation"

    def test_empty_input(self) -> None:
        assert normalize_for_compare("") == ""


class TestNormalizeLine:
    def test_masks_digits_so_page_numbers_collapse(self) -> None:
        assert normalize_line("Page 3 of 27") == normalize_line("Page 17 of 27")

    def test_distinct_text_stays_distinct(self) -> None:
        assert normalize_line("Page 3 of 27") != normalize_line("Section 3 of 27")


class TestCriticalTokens:
    def test_extracts_instrument_tags_and_units(self) -> None:
        tokens = critical_tokens("Transmitter FT-101 uses a 4-20 mA signal at 24 V DC per ISA-5.1.")
        assert "FT-101" in tokens
        assert "ISA-5.1" in tokens
        assert "20mA" in tokens

    def test_preserves_ampersand_acronyms(self) -> None:
        assert "P&ID" in critical_tokens("Refer to the P&ID and the C&I scope.")
        assert "C&I" in critical_tokens("Refer to the P&ID and the C&I scope.")

    def test_does_not_split_tags_into_fragments(self) -> None:
        """``FT-101`` must not also yield a bogus ``-101`` or ``101`` number token."""
        tokens = critical_tokens("Transmitter FT-101 only.")
        assert "FT-101" in tokens
        assert "-101" not in tokens
        assert "101" not in tokens

    def test_case_is_preserved(self) -> None:
        """``PID`` and ``pid`` are different claims in an instrumentation document."""
        assert "PID" in critical_tokens("The PID controller.")
        assert "PID" not in critical_tokens("The pid controller.")

    def test_single_digits_are_not_critical(self) -> None:
        assert critical_tokens("a 5 b") == set()

    def test_percentages_survive(self) -> None:
        assert "0.5%" in critical_tokens("Accuracy is 0.5% of span.")

    def test_empty_input(self) -> None:
        assert critical_tokens("") == set()


class TestSimilarityMetrics:
    def test_jaccard_identical(self) -> None:
        assert jaccard(["a", "b"], ["a", "b"]) == 1.0

    def test_jaccard_disjoint(self) -> None:
        assert jaccard(["a"], ["b"]) == 0.0

    def test_jaccard_two_empties_are_identical(self) -> None:
        assert jaccard([], []) == 1.0

    def test_recall_ignores_additions(self) -> None:
        """Extra parsed tokens are not a defect and must not lower recall."""
        assert token_recall(["a", "b"], ["a", "b", "c", "d"]) == 1.0

    def test_recall_detects_loss(self) -> None:
        assert token_recall(["a", "b", "c", "d"], ["a", "b"]) == 0.5

    def test_recall_of_empty_source_is_one(self) -> None:
        assert token_recall([], ["a"]) == 1.0

    @pytest.mark.parametrize(
        ("source", "parsed", "expected"),
        [(100, 100, 1.0), (100, 50, 0.5), (0, 10, 1.0), (10, 100, 2.0)],
    )
    def test_char_coverage(self, source: int, parsed: int, expected: float) -> None:
        assert char_coverage(source, parsed) == expected


class TestSpanAnalysis:
    def test_finds_missing_paragraph(self) -> None:
        source = "The instrument index maps every tag to a channel. A second sentence entirely absent here."
        parsed = "The instrument index maps every tag to a channel."
        missing = find_missing_spans(source, parsed, min_words=5)
        assert len(missing) == 1
        assert "second sentence" in missing[0]

    def test_tolerates_reordering_and_rewrapping(self) -> None:
        source = "The instrument index maps every tag number to a specific channel."
        parsed = "The instrument index maps every tag\nnumber to a specific channel."
        assert find_missing_spans(source, parsed, min_words=5) == []

    def test_detects_duplicated_span(self) -> None:
        text = "This sentence repeats verbatim here. This sentence repeats verbatim here."
        assert len(find_duplicated_spans(text, min_words=4)) == 1

    def test_no_duplicates_in_clean_text(self) -> None:
        assert find_duplicated_spans("One unique sentence only appears here.", min_words=4) == []

    def test_sentence_spans_respects_min_words(self) -> None:
        assert sentence_spans("Too short. This one has enough words to count.", min_words=5) == [
            "This one has enough words to count."
        ]


class TestHelpers:
    def test_text_sha256_is_normalisation_stable(self) -> None:
        assert text_sha256("Hello   World") == text_sha256("hello world")

    def test_word_tokens_keeps_underscored_tags(self) -> None:
        assert "ft_101" in word_tokens(normalize_for_compare("Sensor FT_101 reads."))

    def test_redact_truncates(self) -> None:
        assert redact("x" * 500, 10) == "x" * 10 + "…"

    def test_redact_can_be_disabled(self) -> None:
        assert redact("x" * 500, 10, enabled=False) == "x" * 500

    def test_dedupe_preserves_order(self) -> None:
        assert dedupe_preserving_order(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]

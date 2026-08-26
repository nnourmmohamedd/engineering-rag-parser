from __future__ import annotations

import pytest

from engineering_rag.services.context_builder.config import TokenizerConfig
from engineering_rag.services.context_builder.token_counter import (
    ConservativeFallbackTokenCounter,
    get_token_counter,
)
from tests.conftest import requires_qwen3_tokenizer


class TestConservativeFallback:
    def test_empty_text_is_zero(self) -> None:
        counter = ConservativeFallbackTokenCounter(chars_per_token=3.0)
        assert counter.count("") == 0

    def test_deterministic(self) -> None:
        counter = ConservativeFallbackTokenCounter(chars_per_token=3.0)
        text = "one two three four five"
        assert counter.count(text) == counter.count(text)

    def test_always_over_counts_relative_to_a_generous_ratio(self) -> None:
        # A 3.0 chars/token fallback must never under-count relative to a typical
        # ~4 chars/token English-text ratio, so it never lets more text through
        # than a real tokenizer's budget would allow.
        counter = ConservativeFallbackTokenCounter(chars_per_token=3.0)
        text = "The instrumentation and control engineering process defines FT-101 P&ID."
        generous_estimate = len(text) / 4.0
        assert counter.count(text) >= generous_estimate

    def test_is_not_exact(self) -> None:
        counter = ConservativeFallbackTokenCounter(chars_per_token=3.0)
        assert counter.is_exact is False

    def test_unicode_text_counted(self) -> None:
        counter = ConservativeFallbackTokenCounter(chars_per_token=3.0)
        assert counter.count("café résumé naïve") > 0

    def test_long_text(self) -> None:
        counter = ConservativeFallbackTokenCounter(chars_per_token=3.0)
        text = "word " * 5000
        assert counter.count(text) > 1000

    def test_invalid_chars_per_token_rejected(self) -> None:
        with pytest.raises(ValueError):
            ConservativeFallbackTokenCounter(chars_per_token=0)

    def test_via_get_token_counter_factory(self) -> None:
        config = TokenizerConfig(backend="conservative_fallback", chars_per_token_fallback=3.0)
        counter = get_token_counter(config)
        assert counter.count("abcdef") == 2


@requires_qwen3_tokenizer
class TestQwen3TokenCounter:
    """Requires network access (or a pre-populated HF cache) on first use; see conftest.py."""

    def test_exact_counts_are_deterministic(self) -> None:
        config = TokenizerConfig(backend="qwen3")
        counter = get_token_counter(config)
        text = "FEED develops the control philosophy and major design deliverables."
        assert counter.count(text) == counter.count(text)
        assert counter.is_exact is True

    def test_empty_text_is_zero(self) -> None:
        config = TokenizerConfig(backend="qwen3")
        counter = get_token_counter(config)
        assert counter.count("") == 0

    def test_engineering_identifiers(self) -> None:
        config = TokenizerConfig(backend="qwen3")
        counter = get_token_counter(config)
        assert counter.count("FT-101 P&ID C&I IEC 61511") > 0

    def test_description_includes_model_and_revision(self) -> None:
        config = TokenizerConfig(backend="qwen3")
        counter = get_token_counter(config)
        assert "Qwen/Qwen3-8B" in counter.description

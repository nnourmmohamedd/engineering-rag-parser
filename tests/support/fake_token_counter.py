"""A deterministic, network-free fake implementing :class:`TokenCounter`.

Used by every fast test that exercises ``services/context_builder`` without
downloading the real Qwen3 tokenizer. Counts whitespace-split words, times a
configurable multiplier -- deterministic and simple to reason about in test
assertions, never claimed to be exact (``is_exact = False``).
"""

from __future__ import annotations

from engineering_rag.services.context_builder.token_counter import TokenCounter

__all__ = ["FakeTokenCounter"]


class FakeTokenCounter(TokenCounter):
    is_exact = False

    def __init__(self, tokens_per_word: float = 1.0) -> None:
        self._tokens_per_word = tokens_per_word
        self.calls: list[str] = []

    def count(self, text: str) -> int:
        self.calls.append(text)
        if not text:
            return 0
        return max(1, round(len(text.split()) * self._tokens_per_word))

    @property
    def description(self) -> str:
        return f"fake:tokens_per_word={self._tokens_per_word}"

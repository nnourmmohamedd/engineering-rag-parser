"""Tokenizer-aware size measurement for context budgeting.

Mirrors ``services/chunker/tokenizer.py``'s wrapper pattern, but scoped to
this package and pinned to the answering model family (Qwen3) rather than the
embedding model. Never approximates when the production tokenizer is
available: :class:`Qwen3TokenCounter` measures exactly what the Qwen3
tokenizer would encode. :class:`ConservativeFallbackTokenCounter` is an
explicit, honestly-labeled, deterministic approximation for use when the
production tokenizer cannot be loaded (see
:class:`~.config.TokenizerConfig`'s docstring) -- it always over-counts, never
under-counts, so a budget check against it never lets more text through than
the real tokenizer would allow.
"""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from functools import lru_cache

from .config import TokenizerConfig
from .errors import TokenizerLoadError

__all__ = [
    "ConservativeFallbackTokenCounter",
    "Qwen3TokenCounter",
    "TokenCounter",
    "get_token_counter",
]

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    "The 'transformers' package (and network access to Hugging Face Hub on first use, or a "
    "pre-populated local cache / HF_HUB_OFFLINE=1 with the tokenizer already cached) is required "
    'for exact Qwen3 token counting. Install it with `pip install -e ".[chunking]"` (already declares '
    "transformers) or set context_builder.tokenizer.backend: conservative_fallback."
)


class TokenCounter(ABC):
    """Counts tokens for a piece of text under some specific measurement."""

    #: True only for a counter that measures exactly what the target LLM's own
    #: tokenizer would produce. False for any approximation, however good.
    is_exact: bool

    @abstractmethod
    def count(self, text: str) -> int:
        """Return the token count for ``text``. Must be deterministic and >= 0."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Short, human-readable identity of this counter (name + revision or method), for manifests/logs."""


class Qwen3TokenCounter(TokenCounter):
    """Exact token counts under the real ``Qwen/Qwen3-8B`` tokenizer (files only, no model weights)."""

    is_exact = True

    def __init__(self, model_name: str, *, revision: str | None, trust_remote_code: bool) -> None:
        self._model_name = model_name
        self._revision = revision
        try:
            from transformers import AutoTokenizer
        except ImportError as exc:  # pragma: no cover - exercised only without the extra installed
            raise TokenizerLoadError(_INSTALL_HINT) from exc

        try:
            self._tokenizer = AutoTokenizer.from_pretrained(
                model_name, revision=revision, trust_remote_code=trust_remote_code
            )
        except Exception as exc:  # noqa: BLE001 - surface a clear, actionable message
            raise TokenizerLoadError(
                f"Could not load tokenizer {model_name!r} (revision={revision!r}). If this is a network "
                f"error, cache the tokenizer once while online, or set HF_HUB_OFFLINE=1 once cached, or "
                f"fall back to context_builder.tokenizer.backend: conservative_fallback. {_INSTALL_HINT}"
            ) from exc

    def count(self, text: str) -> int:
        if not text:
            return 0
        return len(self._tokenizer.encode(text, add_special_tokens=False))

    @property
    def description(self) -> str:
        return f"qwen3:{self._model_name}@{self._revision or 'default'}"


class ConservativeFallbackTokenCounter(TokenCounter):
    """Deterministic, network-free over-estimate. NOT an exact token count -- see module docstring."""

    is_exact = False

    def __init__(self, chars_per_token: float) -> None:
        if chars_per_token <= 0:
            raise ValueError("chars_per_token must be > 0")
        self._chars_per_token = chars_per_token

    def count(self, text: str) -> int:
        if not text:
            return 0
        return math.ceil(len(text) / self._chars_per_token)

    @property
    def description(self) -> str:
        return f"conservative_fallback:chars_per_token={self._chars_per_token}"


@lru_cache(maxsize=4)
def _cached_qwen3_counter(
    model_name: str, revision: str | None, trust_remote_code: bool
) -> Qwen3TokenCounter:
    logger.info("Loading Qwen3 token counter %s (revision=%s)", model_name, revision or "default")
    return Qwen3TokenCounter(model_name, revision=revision, trust_remote_code=trust_remote_code)


def get_token_counter(config: TokenizerConfig) -> TokenCounter:
    """Return the configured :class:`TokenCounter`.

    Raises:
        TokenizerLoadError: ``backend == "qwen3"`` and the tokenizer cannot
            be loaded (network failure with no cache, or missing
            ``transformers``). Never silently substitutes the fallback --
            an operator must explicitly choose it via config.
    """
    if config.backend == "conservative_fallback":
        return ConservativeFallbackTokenCounter(config.chars_per_token_fallback)
    return _cached_qwen3_counter(config.model_name, config.revision, config.trust_remote_code)

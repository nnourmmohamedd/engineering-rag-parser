"""Tokenizer-aware size measurement.

The chunker never approximates size by character count when a tokenizer is
available: every chunk's ``token_count`` is measured with the exact tokenizer
configured for the target embedding model (:class:`~.config.TokenizerOptions`),
so a chunk that "fits" here actually fits inside that model's real input
window.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache

from .config import TokenizerOptions

__all__ = ["ChunkTokenizer", "get_tokenizer"]

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    "The 'transformers' package (and network access to Hugging Face Hub, or a "
    "pre-populated local cache / HF_HUB_OFFLINE=1 with the tokenizer already "
    "cached) is required for chunker tokenization. Install it with "
    '`pip install -e ".[chunking]"`. To pre-cache a tokenizer for offline use: '
    '`python -c "from transformers import AutoTokenizer; '
    "AutoTokenizer.from_pretrained('<model-name>')\"` while online once."
)


class ChunkTokenizer:
    """Thin, picklable-free wrapper around a Hugging Face tokenizer.

    Exposes only what the chunker needs (``count`` and ``max_tokens``) so the
    rest of the codebase never imports ``transformers`` directly.
    """

    def __init__(self, name: str, *, revision: str | None = None, trust_remote_code: bool = False) -> None:
        self.name = name
        try:
            from transformers import AutoTokenizer
        except ImportError as exc:  # pragma: no cover - exercised only without the extra installed
            raise ImportError(_INSTALL_HINT) from exc

        try:
            self._tokenizer = AutoTokenizer.from_pretrained(
                name, revision=revision, trust_remote_code=trust_remote_code
            )
        except Exception as exc:  # noqa: BLE001 - surface a clear, actionable message
            raise RuntimeError(
                f"Could not load tokenizer {name!r}. If this is a network error, cache the "
                f"tokenizer once while online, or set HF_HUB_OFFLINE=1 once it is cached. "
                f"{_INSTALL_HINT}"
            ) from exc

    def count(self, text: str) -> int:
        """Number of tokens ``text`` measures as, per this tokenizer."""
        if not text:
            return 0
        return len(self._tokenizer.encode(text, add_special_tokens=False))

    def length_function(self) -> Callable[[str], int]:
        """A plain ``str -> int`` callable, e.g. for langchain-text-splitters' ``length_function``."""
        return self.count


@lru_cache(maxsize=8)
def _cached_tokenizer(name: str, revision: str | None, trust_remote_code: bool) -> ChunkTokenizer:
    logger.info("Loading tokenizer %s (revision=%s)", name, revision or "default")
    return ChunkTokenizer(name, revision=revision, trust_remote_code=trust_remote_code)


def get_tokenizer(options: TokenizerOptions) -> ChunkTokenizer:
    """Return a cached :class:`ChunkTokenizer` for ``options``.

    Cached process-wide by (name, revision, trust_remote_code) so a run that
    tokenizes thousands of chunks loads the underlying HF tokenizer once.
    """
    return _cached_tokenizer(options.name, options.revision, options.trust_remote_code)

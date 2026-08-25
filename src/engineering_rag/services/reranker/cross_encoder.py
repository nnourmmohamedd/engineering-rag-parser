"""Production reranker: ``BAAI/bge-reranker-base`` via ``sentence_transformers.CrossEncoder``.

Loaded lazily — construction happens only when reranking is enabled
(``pipelines/retrieval_pipeline.py``) — and reused across every query in one
process. Runs fully local and offline-capable (standard Hugging Face cache,
no API, no hosted endpoint). CPU is fully supported; ``device="auto"``
mirrors ``services/embedder/bge.py``'s CUDA-if-available behavior.
"""

from __future__ import annotations

import logging
import time

from .config import RerankerConfig
from .errors import RerankerModelLoadError
from .interface import Reranker
from .models import RerankCandidate, RerankResult

__all__ = ["CrossEncoderReranker"]

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    "The 'sentence-transformers' package (and network access to Hugging Face Hub on first use, "
    'or a pre-populated local cache) is required. Install it with pip install -e ".[indexing]".'
)


class CrossEncoderReranker(Reranker):
    """Loads the cross-encoder once; ``rerank()`` never reloads it."""

    def __init__(self, config: RerankerConfig) -> None:
        self._config = config
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RerankerModelLoadError(_INSTALL_HINT) from exc

        device = _resolve_device(config.device)
        logger.info(
            "Loading reranker model %s (revision=%s) on device=%s",
            config.model_name,
            config.model_revision,
            device,
        )
        started = time.perf_counter()
        try:
            self._model = CrossEncoder(
                config.model_name,
                revision=config.model_revision,
                max_length=config.max_length,
                device=device,
            )
        except Exception as exc:  # noqa: BLE001 - surface a clean, actionable message
            raise RerankerModelLoadError(
                f"Could not load reranker model {config.model_name!r} (revision={config.model_revision!r}). "
                f"If this is a network error, retry online once, or pre-cache the model. {_INSTALL_HINT}"
            ) from exc
        self._load_duration_s = round(time.perf_counter() - started, 4)
        self._device = device
        logger.info("Reranker model loaded in %.2fs on device=%s", self._load_duration_s, device)

    @property
    def load_duration_s(self) -> float:
        return self._load_duration_s

    def rerank(self, query: str, candidates: list[RerankCandidate]) -> list[RerankResult]:
        """Score every candidate jointly with ``query``. Empty ``candidates`` returns ``[]`` without loading."""
        if not candidates:
            return []

        pairs = [(query, c.text) for c in candidates]
        started = time.perf_counter()
        scores = self._model.predict(
            pairs,
            batch_size=self._config.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        duration = time.perf_counter() - started
        logger.info(
            "Reranked %d candidate(s) in %.3fs (%.1f pairs/s) on device=%s",
            len(candidates),
            duration,
            len(candidates) / duration if duration > 0 else 0.0,
            self._device,
        )

        scored = sorted(
            zip(candidates, (float(s) for s in scores), strict=True), key=lambda cs: (-cs[1], cs[0].chunk_id)
        )
        return [
            RerankResult(chunk_id=c.chunk_id, rank=rank, score=score)
            for rank, (c, score) in enumerate(scored, start=1)
        ]


def _resolve_device(requested: str) -> str:
    if requested != "auto":
        return requested
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except ImportError:  # pragma: no cover - torch always present via sentence-transformers
        pass
    return "cpu"

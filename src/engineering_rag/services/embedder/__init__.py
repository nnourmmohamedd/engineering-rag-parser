"""Public interface of the embedding service.

Preferred surface: :class:`EmbeddingService` (the typed ABC), the production
:class:`BGEEmbeddingService`, :class:`EmbedderConfig`, and the error
vocabulary. Depends on nothing under ``databases/`` — this package never
imports ``chromadb``.
"""

from __future__ import annotations

from engineering_rag import __version__

__all__ = [
    "EMBEDDER_VERSION",
    "BGEEmbeddingService",
    "EmbedderConfig",
    "EmbeddingBatchStats",
    "EmbeddingError",
    "EmbeddingRecord",
    "EmbeddingService",
    "EmptyQueryError",
    "ModelInfo",
    "ModelLoadError",
    "VectorValidationError",
    "load_config",
]

#: Bumped whenever embedding semantics change in a way that would alter
#: artifacts for identical input+config. Recorded in every index manifest.
EMBEDDER_VERSION = __version__

from .config import EmbedderConfig, load_config  # noqa: E402
from .errors import EmbeddingError, EmptyQueryError, ModelLoadError, VectorValidationError  # noqa: E402
from .interface import EmbeddingService  # noqa: E402
from .models import EmbeddingBatchStats, EmbeddingRecord, ModelInfo  # noqa: E402


def __getattr__(name: str) -> object:
    # Lazily import BGEEmbeddingService: importing sentence-transformers/torch
    # at package-import time would make every unit test pay that cost even
    # when it only needs the typed interface or a fake embedder.
    if name == "BGEEmbeddingService":
        from .bge import BGEEmbeddingService

        return BGEEmbeddingService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

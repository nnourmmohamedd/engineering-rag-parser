"""Cross-encoder reranking service: joint query-document scoring of a small candidate set.

Independent of both ``services/retriever`` and ``databases/chroma`` — it
receives plain ``(query, chunk_id, text)`` candidates and returns ranked
scores, never touching a vector store or a lexical index itself. The
reranker model is loaded lazily and only when reranking is actually enabled
(``pipelines/retrieval_pipeline.py`` never constructs a
:class:`CrossEncoderReranker` for vector-only or hybrid-without-reranker
requests).
"""

from __future__ import annotations

from engineering_rag import __version__

__all__ = [
    "RERANKER_VERSION",
    "RerankCandidate",
    "RerankerConfig",
    "RerankerError",
    "RerankerModelLoadError",
    "RerankResult",
]

#: Bumped whenever reranking semantics change in a way that would alter
#: results for identical input+config.
RERANKER_VERSION = __version__

from .config import RerankerConfig  # noqa: E402
from .errors import RerankerError, RerankerModelLoadError  # noqa: E402
from .models import RerankCandidate, RerankResult  # noqa: E402

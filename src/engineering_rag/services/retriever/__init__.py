"""Vector retrieval service: domain retrieval logic and data contracts.

Depends on :mod:`engineering_rag.services.embedder` (typed interface only)
for query embedding, but never imports ``chromadb`` and never constructs its
own Chroma client — :class:`VectorRetriever` receives an already-opened
collection object from its caller (``pipelines/retrieval_pipeline.py``).
Mirrors ``services/embedder``'s and ``databases/chroma``'s independence: this
package can be unit-tested with a fake embedder and an in-memory Chroma
collection, with no real model download and no persistent database.
"""

from __future__ import annotations

from engineering_rag import __version__

__all__ = [
    "RETRIEVER_VERSION",
    "BM25Retriever",
    "BM25SearchOutcome",
    "CollectionNotFoundError",
    "CorpusCompatibilityError",
    "CorpusCompatibilityReport",
    "EmptyCollectionError",
    "FilterValue",
    "FusedHit",
    "InvalidFilterError",
    "MalformedChromaResponseError",
    "RetrievalDiagnostics",
    "RetrievalError",
    "RetrievalEvaluationCase",
    "RetrievalEvaluationConfig",
    "RetrievalEvaluationResult",
    "RetrievalEvaluationSummary",
    "RetrievalHit",
    "RetrievalRequest",
    "RetrievalResponse",
    "RetrievalSearchConfig",
    "VectorRetriever",
    "build_where_clause",
    "check_corpus_compatibility",
    "query_hash",
    "reciprocal_rank_fusion",
    "require_compatible",
]

#: Bumped whenever retrieval semantics change in a way that would alter
#: results for identical input+config. Recorded in every evaluation report.
RETRIEVER_VERSION = __version__

from .bm25_retriever import BM25Retriever, BM25SearchOutcome  # noqa: E402
from .config import RetrievalEvaluationConfig, RetrievalSearchConfig  # noqa: E402
from .corpus_compat import (  # noqa: E402
    CorpusCompatibilityError,
    CorpusCompatibilityReport,
    check_corpus_compatibility,
    require_compatible,
)
from .errors import (  # noqa: E402
    CollectionNotFoundError,
    EmptyCollectionError,
    InvalidFilterError,
    MalformedChromaResponseError,
    RetrievalError,
)
from .filters import build_where_clause  # noqa: E402
from .fusion import FusedHit, reciprocal_rank_fusion  # noqa: E402
from .models import (  # noqa: E402
    FilterValue,
    RetrievalDiagnostics,
    RetrievalEvaluationCase,
    RetrievalEvaluationResult,
    RetrievalEvaluationSummary,
    RetrievalHit,
    RetrievalRequest,
    RetrievalResponse,
    query_hash,
)
from .retriever import VectorRetriever  # noqa: E402

"""Context-building service: ranked retrieval hits -> a deduplicated, budgeted, citable context.

Independent of ``clients/ollama`` and ``chromadb``. Consumes
:class:`engineering_rag.services.retriever.models.RetrievalResponse` (the
existing, unmodified retrieval contract) and an injected
:class:`~.neighbor_provider.NeighborProvider`; produces a
:class:`~.models.ContextPackage`. See ``README.md`` for the selection
algorithm and ``docs/answering/GROUNDED_ANSWERING_ARCHITECTURE.md`` for the
full rationale.
"""

from __future__ import annotations

from engineering_rag import __version__

__all__ = [
    "CONTEXT_BUILDER_VERSION",
    "CONTEXT_SCHEMA_VERSION",
    "ConservativeFallbackTokenCounter",
    "ContextBuilder",
    "ContextBuilderConfig",
    "ContextBuilderError",
    "ContextPackage",
    "ExcludedCandidate",
    "NeighborChunk",
    "NeighborProvider",
    "Qwen3TokenCounter",
    "SelectedSource",
    "TokenCounter",
    "TokenizerConfig",
    "TokenizerLoadError",
    "get_token_counter",
    "query_hash",
]

#: Bumped whenever context-selection semantics change in a way that would
#: alter the selection for identical input+config.
CONTEXT_BUILDER_VERSION = __version__

from .builder import ContextBuilder  # noqa: E402
from .config import ContextBuilderConfig, TokenizerConfig  # noqa: E402
from .errors import ContextBuilderError, TokenizerLoadError  # noqa: E402
from .models import (  # noqa: E402
    CONTEXT_SCHEMA_VERSION,
    ContextPackage,
    ExcludedCandidate,
    NeighborChunk,
    SelectedSource,
    query_hash,
)
from .neighbor_provider import NeighborProvider  # noqa: E402
from .token_counter import (  # noqa: E402
    ConservativeFallbackTokenCounter,
    Qwen3TokenCounter,
    TokenCounter,
    get_token_counter,
)

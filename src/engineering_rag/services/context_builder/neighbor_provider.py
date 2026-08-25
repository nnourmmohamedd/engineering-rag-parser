"""Typed interface for fetching a single chunk by ID, for optional neighbor expansion.

The context builder must never import ``chromadb`` directly (see the package
docstring in ``__init__.py``). A concrete provider lives outside this
package -- ``pipelines/answering_pipeline.py`` implements
:class:`~engineering_rag.pipelines.answering_pipeline.ChromaNeighborProvider`,
the only module that both opens the live Chroma collection and constructs a
:class:`~.builder.ContextBuilder`, mirroring how
``pipelines/retrieval_pipeline.py`` is the sole module importing both
``services.retriever`` and ``databases.chroma``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import NeighborChunk

__all__ = ["NeighborProvider"]


class NeighborProvider(ABC):
    """Fetches one chunk's full record by ID, for previous/next neighbor expansion only."""

    @abstractmethod
    def get_chunk(self, chunk_id: str) -> NeighborChunk | None:
        """Return the chunk record for ``chunk_id``, or ``None`` if it does not exist.

        Must never create, rebuild, or mutate the underlying store -- this is
        a read-only lookup against the same, already-indexed corpus the
        active retrieval call queried. Never a second, unvalidated database.
        """

"""A deterministic, in-memory fake implementing :class:`NeighborProvider`."""

from __future__ import annotations

from engineering_rag.services.context_builder.models import NeighborChunk
from engineering_rag.services.context_builder.neighbor_provider import NeighborProvider

__all__ = ["FakeNeighborProvider"]


class FakeNeighborProvider(NeighborProvider):
    def __init__(self, chunks: dict[str, NeighborChunk]) -> None:
        self._chunks = chunks
        self.calls: list[str] = []

    def get_chunk(self, chunk_id: str) -> NeighborChunk | None:
        self.calls.append(chunk_id)
        return self._chunks.get(chunk_id)

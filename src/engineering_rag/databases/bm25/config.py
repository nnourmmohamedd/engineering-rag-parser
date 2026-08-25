"""Validated, hashable configuration for the persistent BM25 lexical index.

Mirrors ``databases/chroma/config.py``: frozen, ``extra="forbid"`` pydantic
model. The BM25 index is built from, and must remain compatible with, the
existing Chroma collection's chunks — see
``services/retriever/corpus_compat.py``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["BM25Config"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BM25Config(_Frozen):
    """Where the persistent BM25 index lives and how it scores documents."""

    index_path: str = Field(
        default="data/output/databases/bm25/engineering_documents_v1",
        description="Directory the persistent BM25 index (and its manifest) is written to/read from.",
    )
    method: Literal["lucene", "robertson", "atire", "bm25l", "bm25+"] = Field(
        default="lucene", description="bm25s scoring variant. 'lucene' matches Elasticsearch/Solr defaults."
    )
    k1: float = Field(default=1.2, gt=0, description="BM25 term-frequency saturation constant.")
    b: float = Field(default=0.75, ge=0, le=1, description="BM25 document-length normalization constant.")
    mmap: bool = Field(
        default=True, description="Memory-map the index on load instead of reading it fully into RAM."
    )

    def effective_dict(self) -> dict[str, Any]:
        return json.loads(self.model_dump_json())

    def config_hash(self) -> str:
        payload = json.dumps(self.effective_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

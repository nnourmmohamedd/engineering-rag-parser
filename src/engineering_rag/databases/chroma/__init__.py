"""ChromaDB storage adapter.

The only place in this package tree that imports ``chromadb``. Accepts plain
float vectors (never computes its own embeddings — ``embedding_function=None``
is always passed explicitly) and never imports ``sentence-transformers``.

Preferred surface: :class:`ChromaConfig`, :class:`CollectionIdentity`,
:func:`get_client`, :func:`open_or_create_collection`, :func:`ingest_batch`,
the error vocabulary.
"""

from __future__ import annotations

from .client import get_client
from .collection import open_or_create_collection, rebuild_collection
from .config import ChromaConfig, validate_collection_name
from .errors import (
    ChromaAdapterError,
    CollectionMismatchError,
    DuplicateIdConflictError,
    InvalidCollectionNameError,
)
from .metadata import chroma_safe_metadata
from .models import INDEX_SCHEMA_VERSION, CollectionIdentity, IngestionOutcome
from .repository import content_hash, ingest_batch
from .validation import round_trip_check, self_retrieval_check

__all__ = [
    "INDEX_SCHEMA_VERSION",
    "ChromaAdapterError",
    "ChromaConfig",
    "CollectionIdentity",
    "CollectionMismatchError",
    "DuplicateIdConflictError",
    "IngestionOutcome",
    "InvalidCollectionNameError",
    "chroma_safe_metadata",
    "content_hash",
    "get_client",
    "ingest_batch",
    "open_or_create_collection",
    "rebuild_collection",
    "round_trip_check",
    "self_retrieval_check",
    "validate_collection_name",
]

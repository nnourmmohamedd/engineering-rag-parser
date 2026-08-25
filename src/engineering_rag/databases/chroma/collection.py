"""Collection lifecycle: open-or-create with compatibility enforcement, and destructive rebuild.

No sentence-transformers import anywhere in this package — embeddings arrive
as plain ``list[float]``, never computed here (``embedding_function=None`` is
passed explicitly to every ``get_or_create_collection`` call so Chroma never
silently uses its own default embedding function).
"""

from __future__ import annotations

import logging
from typing import Any

from .config import ChromaConfig
from .errors import CollectionMismatchError
from .models import CollectionIdentity

__all__ = ["open_or_create_collection", "rebuild_collection"]

logger = logging.getLogger(__name__)


def open_or_create_collection(client: Any, config: ChromaConfig, identity: CollectionIdentity) -> Any:
    """Open ``config.collection_name``, creating it with ``identity`` metadata if absent.

    If the collection already exists, its stored identity metadata is
    compared against ``identity``; any disagreement (model, dimension,
    metric, schema version, tokenizer) is a hard failure — never a silent
    overwrite.
    """
    existing_names = {c.name for c in client.list_collections()}
    is_new = config.collection_name not in existing_names

    collection = client.get_or_create_collection(
        name=config.collection_name,
        metadata=identity.as_chroma_metadata() if is_new else None,
        embedding_function=None,
    )

    if not is_new:
        problems = identity.mismatches(dict(collection.metadata or {}))
        if problems:
            persist_dir = client.get_settings().persist_directory
            raise CollectionMismatchError(
                f"Collection {config.collection_name!r} at {persist_dir} is incompatible with the "
                "current run's configuration:\n  " + "\n  ".join(problems)
            )
        logger.info("Opened existing compatible collection %r", config.collection_name)
    else:
        logger.info("Created new collection %r with identity metadata", config.collection_name)

    return collection


def rebuild_collection(client: Any, config: ChromaConfig, identity: CollectionIdentity) -> Any:
    """Destructively delete and recreate ``config.collection_name``. Requires ``--rebuild``."""
    existing_names = {c.name for c in client.list_collections()}
    if config.collection_name in existing_names:
        logger.warning("Rebuilding (deleting + recreating) collection %r", config.collection_name)
        client.delete_collection(name=config.collection_name)
    return client.get_or_create_collection(
        name=config.collection_name,
        metadata=identity.as_chroma_metadata(),
        embedding_function=None,
    )

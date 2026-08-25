"""Persistent Chroma client factory.

Uses ``chromadb.PersistentClient`` (the real 1.5.9 signature, introspected
directly: ``PersistentClient(path, settings=None, tenant=..., database=...)``)
and disables telemetry via ``chromadb.config.Settings(anonymized_telemetry=...)``
— confirmed present as a field on the installed version's ``Settings`` dataclass.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

__all__ = ["get_client"]

logger = logging.getLogger(__name__)


def get_client(persistence_path: Path, *, telemetry: bool = False) -> Any:  # chromadb.ClientAPI
    """Open (or create) a persistent Chroma client rooted at ``persistence_path``."""
    import chromadb
    from chromadb.config import Settings

    persistence_path.mkdir(parents=True, exist_ok=True)
    settings = Settings(anonymized_telemetry=telemetry)
    logger.info("Opening persistent Chroma client at %s (telemetry=%s)", persistence_path, telemetry)
    return chromadb.PersistentClient(path=str(persistence_path), settings=settings)

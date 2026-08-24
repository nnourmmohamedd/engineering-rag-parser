"""Generic file-hashing helpers shared across services.

Kept separate from any one service so a future service (the chunker, a
future client cache) can hash its own artifacts without importing the parser
service.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

__all__ = ["sha256_file"]


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    """Stream a file through SHA-256 without loading it into memory."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()

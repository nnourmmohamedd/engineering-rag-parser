"""Chroma-safe metadata serialization.

ChromaDB 1.5.9 metadata values must be ``str | int | float | bool`` — ``None``
is rejected outright (confirmed by direct introspection: ``collection.add``
raises ``TypeError: Cannot convert Python object to MetadataValue`` for a
``None`` value), and lists/dicts are not accepted natively. This module is
the single place that maps a chunk record onto a Chroma-legal metadata dict:
lists/dicts are JSON-encoded as strings; ``None``/missing values are dropped
(the key is simply absent) rather than sent as ``None``.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["chroma_safe_metadata"]

#: Cap on the JSON-encoded size of any single collapsed (list/dict -> str)
#: metadata value. Chroma has no hard documented limit, but very large
#: per-record metadata degrades HNSW index performance; values beyond this
#: are truncated and flagged so callers can see it happened.
_MAX_JSON_FIELD_CHARS = 4000


def _encode_value(value: Any) -> str | int | float | bool | None:
    """Collapse one Python value to a Chroma-legal scalar, or None to signal "omit"."""
    if value is None:
        return None
    if isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list | tuple | dict):
        if not value:
            return None  # empty list/dict carries no information -> omit
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        if len(encoded) > _MAX_JSON_FIELD_CHARS:
            encoded = encoded[: _MAX_JSON_FIELD_CHARS - 15] + '...(truncated)"'
        return encoded
    return str(value)


def chroma_safe_metadata(fields: dict[str, Any]) -> dict[str, str | int | float | bool]:
    """Convert an arbitrary field dict into a Chroma-legal metadata mapping.

    - ``None`` values and empty list/dict values are omitted entirely (Chroma
      1.5.9 rejects ``None`` metadata values; there is no "null" concept).
    - Lists/dicts are JSON-encoded as compact strings, capped at
      ``_MAX_JSON_FIELD_CHARS`` (truncated values are suffixed
      ``...(truncated)"`` so a consumer can detect it).
    - Every other scalar passes through unchanged.
    """
    result: dict[str, str | int | float | bool] = {}
    for key, value in fields.items():
        encoded = _encode_value(value)
        if encoded is not None:
            result[key] = encoded
    return result

"""Metadata filter validation and translation to Chroma ``where`` clauses.

Chroma 1.5.9's ``where`` argument only matches scalar (``str | int | float |
bool``) equality/comparison against stored metadata values. Several stored
fields (``page_numbers``, ``heading_path``, ``source_element_refs``,
``warnings_summary`` when list-derived) are JSON-encoded strings — see
``databases/chroma/metadata.py`` — so a filter like ``page_numbers=12`` cannot
be expressed as a native Chroma list-membership condition. This module
refuses such filters explicitly rather than silently matching nothing or
fabricating client-side list search.
"""

from __future__ import annotations

from typing import Any

from .config import RetrievalSearchConfig
from .errors import InvalidFilterError

__all__ = ["build_where_clause"]


def build_where_clause(
    filters: dict[str, str | int | float | bool], config: RetrievalSearchConfig
) -> dict[str, Any] | None:
    """Validate ``filters`` against the allowed scalar fields and build a Chroma ``where`` clause.

    Raises:
        InvalidFilterError: if a filter key is not in
            ``config.allowed_metadata_filter_fields``, or a value is not a
            Chroma-legal scalar type.
    """
    if not filters:
        return None

    allowed = set(config.allowed_metadata_filter_fields)
    unsupported = sorted(set(filters) - allowed)
    if unsupported:
        raise InvalidFilterError(
            f"unsupported metadata filter field(s): {unsupported}. Allowed fields: {sorted(allowed)}. "
            "JSON-encoded list fields (page_numbers, heading_path, source_element_refs) are not "
            "supported as native Chroma filters."
        )

    for key, value in filters.items():
        if isinstance(value, bool):
            continue
        if not isinstance(value, str | int | float):
            raise InvalidFilterError(
                f"filter {key!r} has unsupported value type {type(value).__name__}; "
                "only str, int, float, bool scalars are Chroma-legal filter values."
            )

    if len(filters) == 1:
        ((key, value),) = filters.items()
        return {key: value}
    return {"$and": [{key: value} for key, value in sorted(filters.items())]}

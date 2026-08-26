"""Metadata filter validation and translation to Chroma ``where`` clauses.

Chroma 1.5.9's ``where`` argument only matches scalar (``str | int | float |
bool``) equality/comparison against stored metadata values, plus native
``$in`` membership against a list of such scalars. Several stored fields
(``page_numbers``, ``heading_path``, ``source_element_refs``,
``warnings_summary`` when list-derived) are JSON-encoded strings — see
``databases/chroma/metadata.py`` — so a filter like ``page_numbers=12`` cannot
be expressed as a native Chroma list-membership condition. This module
refuses such filters explicitly rather than silently matching nothing or
fabricating client-side list search.

A filter *value* that is a list/tuple means "this field must be one of
these scalars" and becomes a native ``{"field": {"$in": [...]}}`` clause.
That is what scopes a query to a set of selected documents
(``document_id`` is an allowed field), and it is applied by the database at
query time — never by retrieving globally and discarding rows afterwards.
The distinction matters: a JSON-encoded *stored list* is still refused, only
a caller-supplied *set of candidate scalars* is accepted here.
"""

from __future__ import annotations

from typing import Any

from .config import RetrievalSearchConfig
from .errors import InvalidFilterError
from .models import FilterValue

__all__ = ["FilterValue", "build_where_clause"]

_SCALAR_TYPES = (str, int, float)


def _validate_scalar(key: str, value: Any) -> None:
    if isinstance(value, bool):
        return
    if not isinstance(value, _SCALAR_TYPES):
        raise InvalidFilterError(
            f"filter {key!r} has unsupported value type {type(value).__name__}; "
            "only str, int, float, bool scalars (or a list/tuple of them) are "
            "Chroma-legal filter values."
        )


def _condition(key: str, value: FilterValue) -> dict[str, Any]:
    """Translate one (key, value) pair into a Chroma condition."""
    if isinstance(value, list | tuple):
        if not value:
            raise InvalidFilterError(
                f"filter {key!r} was given an empty list; an empty selection matches nothing and is "
                "almost always a caller bug. Pass at least one value, or omit the filter entirely."
            )
        for item in value:
            _validate_scalar(key, item)
        # Deduplicate while preserving caller order, so the emitted clause is stable.
        unique = list(dict.fromkeys(value))
        if len(unique) == 1:
            return {key: unique[0]}
        return {key: {"$in": unique}}
    _validate_scalar(key, value)
    return {key: value}


def build_where_clause(
    filters: dict[str, FilterValue], config: RetrievalSearchConfig
) -> dict[str, Any] | None:
    """Validate ``filters`` against the allowed fields and build a Chroma ``where`` clause.

    A list/tuple value becomes a native ``$in`` membership condition, which is
    how a query is scoped to a set of selected ``document_id`` values.

    Raises:
        InvalidFilterError: if a filter key is not in
            ``config.allowed_metadata_filter_fields``, a value is not a
            Chroma-legal scalar (or list of them), or a list value is empty.
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

    if len(filters) == 1:
        ((key, value),) = filters.items()
        return _condition(key, value)
    return {"$and": [_condition(key, filters[key]) for key in sorted(filters)]}

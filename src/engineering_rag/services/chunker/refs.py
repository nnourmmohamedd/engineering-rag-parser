"""Build a ``self_ref -> DocItem`` index once per document.

Type-specific refinement (tables, figures) needs the *original* Docling item
— not just its serialized text — to do row-aware splitting or to look up an
asset path. Docling does not expose a direct ``self_ref`` lookup, so this
module builds the index once by walking the document a single time.
"""

from __future__ import annotations

from typing import Any

from docling_core.types.doc import DoclingDocument

__all__ = ["build_ref_index"]


def build_ref_index(doc: DoclingDocument) -> dict[str, Any]:
    """Map every item's ``self_ref`` to the item itself."""
    index: dict[str, Any] = {}
    for item, _level in doc.iterate_items(with_groups=True):
        ref = getattr(item, "self_ref", None)
        if ref:
            index[ref] = item
    return index

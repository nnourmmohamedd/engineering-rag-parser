"""Structural inventory of a converted :class:`DoclingDocument`.

Split out of what used to be ``parser.py``: counting headings, lists, tables
and pictures is a distinct responsibility from building the converter and
running the conversion (see :mod:`engineering_rag.services.parser.converter`).
"""

from __future__ import annotations

import logging
from collections import Counter

from docling_core.types.doc import (
    ContentLayer,
    DocItemLabel,
    DoclingDocument,
    PictureItem,
    SectionHeaderItem,
    TableItem,
    TextItem,
)

from .models import DocumentInventory, PageInventory

__all__ = ["build_inventory"]

logger = logging.getLogger(__name__)

_LIST_LABELS = {DocItemLabel.LIST_ITEM}
_FURNITURE_LABELS = {DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER}


def build_inventory(document: DoclingDocument) -> DocumentInventory:
    """Walk the document once and count everything the validators need.

    Furniture (``ContentLayer.FURNITURE``) is counted separately rather than
    skipped, because "what did we classify as furniture" is itself audit
    evidence that the report has to show.
    """
    inv = DocumentInventory(page_count=len(document.pages))
    pages: dict[int, PageInventory] = {int(no): PageInventory(page_no=int(no)) for no in document.pages}
    label_counts: Counter[str] = Counter()
    headings_by_level: Counter[str] = Counter()

    all_layers = {ContentLayer.BODY, ContentLayer.FURNITURE, ContentLayer.BACKGROUND}
    for item, _level in document.iterate_items(with_groups=False, included_content_layers=all_layers):
        label = getattr(item, "label", None)
        label_name = getattr(label, "value", str(label)) if label is not None else "unknown"
        label_counts[label_name] += 1
        inv.items_total += 1

        provs = list(getattr(item, "prov", []) or [])
        if provs:
            inv.items_with_provenance += 1
        page_no = int(provs[0].page_no) if provs else None
        page_inv = pages.get(page_no) if page_no is not None else None
        if page_inv is not None:
            page_inv.has_provenance = True

        is_furniture = getattr(item, "content_layer", None) == ContentLayer.FURNITURE
        if is_furniture:
            inv.furniture_items += 1
            if page_inv:
                page_inv.furniture_items += 1

        if isinstance(item, TableItem):
            inv.tables += 1
            data = getattr(item, "data", None)
            if data is not None:
                inv.table_cells += len(getattr(data, "table_cells", []) or [])
            if page_inv:
                page_inv.tables += 1
            continue

        if isinstance(item, PictureItem):
            inv.pictures += 1
            if page_inv:
                page_inv.pictures += 1
            continue

        text = getattr(item, "text", "") or ""
        inv.total_char_count += len(text)
        if page_inv:
            page_inv.char_count += len(text)
            page_inv.word_count += len(text.split())
            page_inv.text_items += 1

        if label == DocItemLabel.TITLE:
            inv.titles += 1
            headings_by_level["title"] += 1
            if page_inv:
                page_inv.headings += 1
        elif isinstance(item, SectionHeaderItem) or label == DocItemLabel.SECTION_HEADER:
            inv.section_headers += 1
            level = getattr(item, "level", None)
            headings_by_level[f"level_{level}" if level is not None else "level_unknown"] += 1
            if page_inv:
                page_inv.headings += 1
        elif label in _LIST_LABELS:
            inv.list_items += 1
            # `ListItem.enumerated` is the structural field Docling's own Markdown
            # serializer uses to decide "1." vs "-"; it is set per-item (so mixed
            # and nested lists are handled correctly) and does not depend on
            # guessing intent from the `marker` string, which is frequently "-"
            # even for enumerated items (D-6).
            if bool(getattr(item, "enumerated", False)):
                inv.ordered_list_items += 1
            else:
                inv.unordered_list_items += 1
            if page_inv:
                page_inv.list_items += 1
        elif label == DocItemLabel.CAPTION:
            inv.captions += 1
            if page_inv:
                page_inv.captions += 1
        elif label == DocItemLabel.FORMULA:
            inv.formulas += 1
            if page_inv:
                page_inv.formulas += 1
        elif label == DocItemLabel.CODE:
            inv.code_blocks += 1
            if page_inv:
                page_inv.code_blocks += 1
        elif isinstance(item, TextItem) and label not in _FURNITURE_LABELS:
            inv.paragraphs += 1

    inv.headings_by_level = dict(sorted(headings_by_level.items()))
    inv.label_counts = dict(sorted(label_counts.items()))
    inv.pages = [pages[k] for k in sorted(pages)]
    return inv

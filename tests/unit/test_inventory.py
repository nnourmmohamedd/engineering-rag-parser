"""Unit tests for `build_inventory`'s structural counting, built on a minimal
`DoclingDocument` constructed directly (no real Docling conversion needed).
"""

from __future__ import annotations

from docling_core.types.doc import DoclingDocument, GroupLabel

from engineering_rag_parser.parser import build_inventory


def _document_with_lists() -> DoclingDocument:
    doc = DoclingDocument(name="t")
    top = doc.add_group(label=GroupLabel.LIST, name="list")
    doc.add_list_item(text="ordered one", enumerated=True, marker="1.", parent=top)
    doc.add_list_item(text="ordered two", enumerated=True, marker="2.", parent=top)
    nested = doc.add_group(label=GroupLabel.LIST, name="nested", parent=top)
    doc.add_list_item(text="bullet a", enumerated=False, marker="-", parent=nested)
    doc.add_list_item(text="bullet b", enumerated=False, marker="-", parent=nested)
    doc.add_list_item(text="bullet c", enumerated=False, marker="-", parent=nested)
    return doc


class TestListTypeClassification:
    """Regression tests for D-6.

    The previous implementation guessed ordered/unordered from the `marker`
    string, which on the real acceptance document classified all 41 list
    items as ordered even though 31 of them render as Markdown bullets.
    `ListItem.enumerated` is the field Docling's own Markdown serializer
    consults, so the inventory must agree with it instead.
    """

    def test_counts_by_enumerated_field_not_marker_text(self) -> None:
        inv = build_inventory(_document_with_lists())
        assert inv.list_items == 5
        assert inv.ordered_list_items == 2
        assert inv.unordered_list_items == 3

    def test_nested_list_items_are_counted_independently(self) -> None:
        """A bullet sub-list nested inside an ordered list must not inherit its parent's type."""
        inv = build_inventory(_document_with_lists())
        assert inv.ordered_list_items + inv.unordered_list_items == inv.list_items

    def test_all_unordered_when_none_enumerated(self) -> None:
        doc = DoclingDocument(name="t")
        group = doc.add_group(label=GroupLabel.LIST, name="list")
        doc.add_list_item(text="a", enumerated=False, marker="-", parent=group)
        doc.add_list_item(text="b", enumerated=False, marker="-", parent=group)
        inv = build_inventory(doc)
        assert inv.ordered_list_items == 0
        assert inv.unordered_list_items == 2

    def test_all_ordered_when_all_enumerated(self) -> None:
        doc = DoclingDocument(name="t")
        group = doc.add_group(label=GroupLabel.ORDERED_LIST, name="list")
        doc.add_list_item(text="a", enumerated=True, marker="1.", parent=group)
        doc.add_list_item(text="b", enumerated=True, marker="2.", parent=group)
        inv = build_inventory(doc)
        assert inv.ordered_list_items == 2
        assert inv.unordered_list_items == 0

    def test_marker_text_alone_does_not_determine_type(self) -> None:
        """A misleading marker string must not override the structural `enumerated` flag."""
        doc = DoclingDocument(name="t")
        group = doc.add_group(label=GroupLabel.LIST, name="list")
        # A bullet-rendered item whose marker text still looks numeric.
        doc.add_list_item(text="a", enumerated=False, marker="1)", parent=group)
        inv = build_inventory(doc)
        assert inv.ordered_list_items == 0
        assert inv.unordered_list_items == 1

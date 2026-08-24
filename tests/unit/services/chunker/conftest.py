"""Synthetic DoclingDocument fixtures for chunker tests.

Built directly via the DoclingDocument API (no PDF, no Docling conversion,
no model weights) — legal, minimal documents covering every content type the
chunker must handle, plus edge cases (oversized text/table, Unicode,
multi-page provenance).
"""

from __future__ import annotations

import pytest
from docling_core.types.doc import (
    BoundingBox,
    CoordOrigin,
    DocItemLabel,
    DoclingDocument,
    ProvenanceItem,
    Size,
    TableCell,
    TableData,
)


def _prov(page_no: int, top: float = 700.0) -> ProvenanceItem:
    return ProvenanceItem(
        page_no=page_no,
        bbox=BoundingBox(l=36.0, t=top, r=500.0, b=top - 20.0, coord_origin=CoordOrigin.BOTTOMLEFT),
        charspan=(0, 10),
    )


def build_sample_document() -> DoclingDocument:
    """A small, legal DoclingDocument exercising every content type."""
    doc = DoclingDocument(name="sample")
    for page_no in (1, 2, 3):
        doc.add_page(page_no=page_no, size=Size(width=595.0, height=842.0))

    doc.add_title("Sample Engineering Specification", prov=_prov(1, 800))

    doc.add_heading("1. Overview", level=1, prov=_prov(1, 760))
    doc.add_text(
        label=DocItemLabel.TEXT,
        text="The transmitter FT-101 provides a 4-20 mA signal at 24 V DC per ISA-5.1. "
        "Unicode check: café, naïve, Zürich, 中文测试.",
        prov=_prov(1, 740),
    )

    doc.add_heading("1.1 Detailed Discussion", level=2, prov=_prov(1, 700))
    long_sentence = (
        "This section intentionally repeats similar engineering language many times so that its "
        "token count exceeds the configured max_tokens threshold, forcing the recursive splitter to "
        "engage on a hierarchical TEXT chunk that would otherwise be a single oversized unit. "
    )
    doc.add_text(
        label=DocItemLabel.TEXT,
        text=long_sentence * 40,
        prov=_prov(1, 680),
    )

    doc.add_heading("2. Instrument Ranges", level=1, prov=_prov(2, 800))
    table_data = TableData(
        num_rows=3,
        num_cols=2,
        table_cells=[
            TableCell(
                text="Tag",
                start_row_offset_idx=0,
                end_row_offset_idx=1,
                start_col_offset_idx=0,
                end_col_offset_idx=1,
                column_header=True,
            ),
            TableCell(
                text="Range",
                start_row_offset_idx=0,
                end_row_offset_idx=1,
                start_col_offset_idx=1,
                end_col_offset_idx=2,
                column_header=True,
            ),
            TableCell(
                text="FT-101",
                start_row_offset_idx=1,
                end_row_offset_idx=2,
                start_col_offset_idx=0,
                end_col_offset_idx=1,
            ),
            TableCell(
                text="0-100 kPa",
                start_row_offset_idx=1,
                end_row_offset_idx=2,
                start_col_offset_idx=1,
                end_col_offset_idx=2,
            ),
            TableCell(
                text="PT-202",
                start_row_offset_idx=2,
                end_row_offset_idx=3,
                start_col_offset_idx=0,
                end_col_offset_idx=1,
            ),
            TableCell(
                text="0-16 bar",
                start_row_offset_idx=2,
                end_row_offset_idx=3,
                start_col_offset_idx=1,
                end_col_offset_idx=2,
            ),
        ],
    )
    doc.add_table(data=table_data, prov=_prov(2, 760))

    doc.add_heading("2.1 Requirements", level=2, prov=_prov(2, 700))
    list_group = doc.add_list_group()
    doc.add_list_item(
        "First requirement: calibrate FT-101 annually.",
        enumerated=True,
        marker="1.",
        parent=list_group,
        prov=_prov(2, 680),
    )
    doc.add_list_item(
        "Second requirement: verify PT-202 range.",
        enumerated=True,
        marker="2.",
        parent=list_group,
        prov=_prov(2, 660),
    )
    doc.add_list_item(
        "Third requirement: log all changes.",
        enumerated=True,
        marker="3.",
        parent=list_group,
        prov=_prov(2, 640),
    )

    doc.add_heading("3. Control Snippet", level=1, prov=_prov(3, 800))
    doc.add_code(
        text="def read_ft101():\n    return sensor.read('FT-101')\n",
        prov=_prov(3, 760),
    )

    doc.add_heading("3.1 Governing Equation", level=2, prov=_prov(3, 700))
    doc.add_formula(text="f(x) = \\int_0^\\infty e^{-x^2} dx = \\sqrt{\\pi}/2", prov=_prov(3, 680))

    doc.add_heading("3.2 Loop Diagram", level=2, prov=_prov(3, 620))
    doc.add_picture(prov=_prov(3, 600))

    return doc


def build_oversized_table_document() -> DoclingDocument:
    """A DoclingDocument with a table too large to fit in one chunk."""
    doc = DoclingDocument(name="big-table")
    doc.add_page(page_no=1, size=Size(width=595.0, height=842.0))
    doc.add_heading("Large Table", level=1, prov=_prov(1, 800))

    n_rows = 40
    cells = [
        TableCell(
            text="Instrument Tag",
            start_row_offset_idx=0,
            end_row_offset_idx=1,
            start_col_offset_idx=0,
            end_col_offset_idx=1,
            column_header=True,
        ),
        TableCell(
            text="Description and Notes",
            start_row_offset_idx=0,
            end_row_offset_idx=1,
            start_col_offset_idx=1,
            end_col_offset_idx=2,
            column_header=True,
        ),
    ]
    for i in range(1, n_rows + 1):
        cells.append(
            TableCell(
                text=f"FT-{100 + i}",
                start_row_offset_idx=i,
                end_row_offset_idx=i + 1,
                start_col_offset_idx=0,
                end_col_offset_idx=1,
            )
        )
        cells.append(
            TableCell(
                text=(
                    f"Flow transmitter number {i}, calibrated range 0-{100 + i} kPa, installed on line "
                    f"{i} per ISA-5.1 tagging conventions and P&ID reference sheet {i}."
                ),
                start_row_offset_idx=i,
                end_row_offset_idx=i + 1,
                start_col_offset_idx=1,
                end_col_offset_idx=2,
            )
        )
    table_data = TableData(num_rows=n_rows + 1, num_cols=2, table_cells=cells)
    doc.add_table(data=table_data, prov=_prov(1, 760))
    return doc


@pytest.fixture
def sample_document() -> DoclingDocument:
    return build_sample_document()


@pytest.fixture
def oversized_table_document() -> DoclingDocument:
    return build_oversized_table_document()

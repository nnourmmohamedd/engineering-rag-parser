"""Stage 1: hierarchical, document-structure-aware chunking.

Wraps Docling's own :class:`~docling_core.transforms.chunker.HierarchicalChunker`
— the Docling-native mechanism for this — and converts its output into this
service's :class:`~.internal.WorkingChunk` representation, classifying each
chunk's content type from the underlying Docling item labels.

Docling's ``HierarchicalChunker`` silently drops any picture that serializes
to empty text (an uncaptioned figure, which is the common case for
engineering diagrams). Those are recovered separately in
:mod:`.type_handlers.figures`, using the parser's own picture classification
(``validation/report.json``, when available) so decorative repeated banner
fragments are not turned into noise chunks.
"""

from __future__ import annotations

import logging

from docling_core.transforms.chunker import DocChunk, HierarchicalChunker
from docling_core.types.doc import (
    CodeItem,
    DocItemLabel,
    DoclingDocument,
    FormulaItem,
    ListItem,
    TableItem,
)

from .internal import WorkingChunk
from .models import ContentType, ProvenanceRecord, SplitMethod, TableFragmentMeta

__all__ = ["build_hierarchical_chunks"]

logger = logging.getLogger(__name__)


def _classify(doc_chunk: DocChunk) -> ContentType:
    """Decide a chunk's content type from the Docling item(s) it was built from."""
    items = doc_chunk.meta.doc_items
    if any(isinstance(it, TableItem) for it in items):
        return ContentType.TABLE
    if any(isinstance(it, FormulaItem) for it in items):
        return ContentType.EQUATION
    if any(isinstance(it, CodeItem) for it in items):
        return ContentType.CODE
    if any(isinstance(it, ListItem) or getattr(it, "label", None) == DocItemLabel.LIST_ITEM for it in items):
        return ContentType.LIST
    return ContentType.TEXT


def _provenance(items: list) -> tuple[list[ProvenanceRecord], list[int]]:
    records: list[ProvenanceRecord] = []
    pages: list[int] = []
    for item in items:
        for prov in getattr(item, "prov", []) or []:
            page_no = int(prov.page_no)
            pages.append(page_no)
            bbox = prov.bbox
            records.append(
                ProvenanceRecord(
                    page_no=page_no,
                    bbox=(float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b)) if bbox else None,
                    charspan=tuple(prov.charspan) if getattr(prov, "charspan", None) else None,
                )
            )
    ordered_unique_pages = sorted(set(pages))
    return records, ordered_unique_pages


def _captions(doc: DoclingDocument, items: list) -> list[str]:
    captions: list[str] = []
    for item in items:
        caption_fn = getattr(item, "caption_text", None)
        if caption_fn is None:
            continue
        try:
            text = caption_fn(doc)
        except Exception:  # noqa: BLE001 - caption extraction must never abort chunking
            text = ""
        if text and text not in captions:
            captions.append(text)
    return captions


def _table_metadata(doc_chunk: DocChunk) -> TableFragmentMeta | None:
    tables = [it for it in doc_chunk.meta.doc_items if isinstance(it, TableItem)]
    if not tables:
        return None
    table = tables[0]
    return TableFragmentMeta(
        num_rows=int(table.data.num_rows),
        num_cols=int(table.data.num_cols),
    )


def build_hierarchical_chunks(doc: DoclingDocument) -> list[WorkingChunk]:
    """Run Docling's HierarchicalChunker and convert its output to WorkingChunks.

    Each chunk carries the heading/section path that contextualises it —
    Docling's serializer already resolves that per chunk via ``meta.headings``.
    """
    chunker = HierarchicalChunker(always_emit_headings=False)
    working_chunks: list[WorkingChunk] = []

    for base_chunk in chunker.chunk(doc):
        if not isinstance(
            base_chunk, DocChunk
        ):  # pragma: no cover - HierarchicalChunker always yields DocChunk
            continue
        doc_chunk = base_chunk
        if not doc_chunk.text.strip():
            continue
        items = doc_chunk.meta.doc_items
        content_type = _classify(doc_chunk)
        provenance, pages = _provenance(items)
        captions = _captions(doc, items)
        label_values = {label.value for it in items if (label := getattr(it, "label", None)) is not None}
        labels = sorted(label_values)
        heading_path = list(doc_chunk.meta.headings or [])
        section_title = heading_path[-1] if heading_path else None
        refs = [it.self_ref for it in items]

        working_chunks.append(
            WorkingChunk(
                text=doc_chunk.text,
                content_type=content_type,
                heading_path=heading_path,
                section_title=section_title,
                captions=captions,
                labels=labels,
                page_numbers=pages,
                provenance=provenance,
                source_element_refs=refs,
                split_method=SplitMethod.HIERARCHICAL,
                table_metadata=_table_metadata(doc_chunk) if content_type is ContentType.TABLE else None,
            )
        )

    logger.info(
        "Hierarchical chunking: %d initial chunk(s) from %d page(s)", len(working_chunks), len(doc.pages)
    )
    return working_chunks

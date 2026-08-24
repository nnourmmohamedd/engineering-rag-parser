"""Figure refinement: build FIGURE chunks directly from ``doc.pictures``.

Docling's ``HierarchicalChunker`` silently drops any picture that serializes
to empty text — which is every uncaptioned figure, the common case for
engineering diagrams. This module builds a FIGURE chunk for every picture
directly instead, so no substantive figure goes unrepresented.

When the parser's own ``validation/report.json`` is available (it usually is,
since the chunker's canonical input lives alongside it in a parser run
directory), picture classification (substantive vs. decorative-repeated) and
warnings are read from there — the same evidence the parser already produced
— rather than re-deriving decorative-image detection from scratch. Without
it, every picture with any provenance is treated as a candidate figure.
"""

from __future__ import annotations

import logging
from typing import Any

from docling_core.types.doc import DoclingDocument

from engineering_rag.services.chunker.config import ChunkerConfig
from engineering_rag.services.chunker.internal import WorkingChunk
from engineering_rag.services.chunker.models import ContentType, ProvenanceRecord, SplitMethod
from engineering_rag.services.chunker.tokenizer import ChunkTokenizer

__all__ = ["build_figure_chunks"]

logger = logging.getLogger(__name__)


def _picture_findings_by_ref(validation_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    findings: dict[str, dict[str, Any]] = {}
    for entry in validation_report.get("pictures", []) or []:
        ref = entry.get("self_ref")
        if ref:
            findings[ref] = entry
    return findings


def build_figure_chunks(
    doc: DoclingDocument,
    *,
    config: ChunkerConfig,
    tokenizer: ChunkTokenizer,
    validation_report: dict[str, Any],
) -> list[WorkingChunk]:
    """One FIGURE chunk per substantive picture (all pictures, if no parser report is available)."""
    findings = _picture_findings_by_ref(validation_report)
    chunks: list[WorkingChunk] = []

    for picture in doc.pictures:
        finding = findings.get(picture.self_ref)
        if findings and (finding is None or finding.get("classification") == "decorative_repeated"):
            continue  # decorative repeat, already identified and excluded by the parser

        try:
            caption = (picture.caption_text(doc) or "").strip()
        except Exception:  # noqa: BLE001 - caption extraction must never abort chunking
            caption = ""

        page_no = None
        provenance: list[ProvenanceRecord] = []
        for prov in picture.prov or []:
            page_no = int(prov.page_no)
            bbox = prov.bbox
            provenance.append(
                ProvenanceRecord(
                    page_no=page_no,
                    bbox=(float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b)) if bbox else None,
                    charspan=None,
                )
            )

        asset_path = finding.get("asset_path") if finding else None
        text = caption or f"[Figure on page {page_no}: no caption or generated description available]"

        warnings: list[str] = []
        parser_warnings: list[str] = []
        if finding:
            for note in finding.get("notes", []) or []:
                parser_warnings.append(note)
            if finding.get("represents_table_label"):
                parser_warnings.append(
                    f"This picture's caption identifies it as '{finding['represents_table_label']}': "
                    "Docling classified this table's body as a picture region, not a table."
                )
        if not caption:
            warnings.append(
                "No caption or parser-generated description exists for this figure; visual content "
                "(diagram labels, symbols, connections) is not represented in text and requires "
                "human visual review."
            )

        token_count = tokenizer.count(text)
        chunks.append(
            WorkingChunk(
                text=text,
                content_type=ContentType.FIGURE,
                heading_path=[],
                section_title=None,
                captions=[caption] if caption else [],
                labels=[picture.label.value],
                page_numbers=[page_no] if page_no is not None else [],
                provenance=provenance,
                source_element_refs=[picture.self_ref],
                split_method=SplitMethod.FIGURE,
                token_count=token_count,
                is_atomic_overflow=token_count > config.max_tokens,
                figure_asset_path=asset_path,
                figure_page_no=page_no,
                warnings=warnings,
                parser_warnings=parser_warnings,
            )
        )

    logger.info(
        "Figure chunks: %d built from %d picture(s) in the document (%s)",
        len(chunks),
        len(doc.pictures),
        "filtered by parser classification" if findings else "no validation report available, all included",
    )
    return chunks

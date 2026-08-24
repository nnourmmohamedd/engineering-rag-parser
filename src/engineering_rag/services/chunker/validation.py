"""Chunk output validation gates.

Separates hard failures (``CRITICAL``, block the run), acceptable warnings
(``WARNING``, downgrade status to ``PASS_WITH_WARNINGS`` unless ``--strict``)
and informational human-review items. A ``PASS_WITH_WARNINGS`` never hides a
failed hard gate — any failed ``CRITICAL`` check forces ``FAIL`` regardless of
how many warnings also exist.

Some spec requirements ("deterministic output across two identical runs")
are inherently a property of *repeated execution*, not of one run's output in
isolation — those are covered by tests (see
``tests/unit/services/chunker/test_service_determinism.py``) rather than by a
gate here, and are listed as such in ``docs/chunker/VALIDATION.md``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docling_core.types.doc import DoclingDocument

from .config import ChunkerConfig
from .ids import chunk_id
from .models import (
    Chunk,
    ChunkValidationCheck,
    ChunkValidationReport,
    ContentType,
    RunStatus,
    Severity,
)

__all__ = ["validate_chunks"]


def _check(
    check_id: str,
    title: str,
    passed: bool,
    severity: Severity,
    *,
    gate: bool,
    summary: str,
    evidence: dict[str, Any] | None = None,
    remediation: str = "",
) -> ChunkValidationCheck:
    return ChunkValidationCheck(
        check_id=check_id,
        title=title,
        passed=passed,
        severity=severity,
        gate=gate,
        summary=summary,
        evidence=evidence or {},
        remediation=remediation,
    )


def validate_chunks(
    chunks: list[Chunk],
    *,
    doc: DoclingDocument,
    document_id: str,
    source_sha256: str,
    config: ChunkerConfig,
    chunks_jsonl_path: Path | None = None,
) -> ChunkValidationReport:
    """Run every validation gate against a finished chunk list."""
    checks: list[ChunkValidationCheck] = []
    human_review: list[str] = []

    # --- structural gates -----------------------------------------------------
    empty = [c.chunk_id for c in chunks if not c.text.strip()]
    checks.append(
        _check(
            "no_empty_chunks",
            "No chunk has empty text",
            not empty,
            Severity.CRITICAL,
            gate=True,
            summary="No empty chunks." if not empty else f"{len(empty)} empty chunk(s): {empty[:5]}",
            evidence={"empty_chunk_ids": empty[:20]},
            remediation="An empty chunk means a refinement stage dropped content; inspect the source element.",
        )
    )

    ids_seen: dict[str, int] = {}
    for c in chunks:
        ids_seen[c.chunk_id] = ids_seen.get(c.chunk_id, 0) + 1
    duplicates = [i for i, n in ids_seen.items() if n > 1]
    checks.append(
        _check(
            "no_duplicate_chunk_ids",
            "No duplicate chunk IDs",
            not duplicates,
            Severity.CRITICAL,
            gate=True,
            summary="All chunk IDs unique." if not duplicates else f"{len(duplicates)} duplicated ID(s).",
            evidence={"duplicate_ids": duplicates[:20]},
            remediation="IDs are content+position derived; a duplicate means two chunks are byte-identical at the same index, which should be impossible.",
        )
    )

    id_mismatches = [
        c.chunk_id
        for c in chunks
        if c.chunk_id != chunk_id(document_id_=document_id, chunk_index=c.chunk_index, text=c.text)
    ]
    checks.append(
        _check(
            "deterministic_ids_recomputable",
            "Every chunk ID recomputes from (document_id, index, text)",
            not id_mismatches,
            Severity.CRITICAL,
            gate=True,
            summary="All IDs recompute correctly."
            if not id_mismatches
            else f"{len(id_mismatches)} mismatch(es).",
            evidence={"mismatched_ids": id_mismatches[:20]},
            remediation="A mismatch means chunk_id was not (re)computed via ids.chunk_id after the final index was assigned.",
        )
    )

    oversized_unflagged = [
        c.chunk_id for c in chunks if c.token_count > config.max_tokens and not c.is_atomic_overflow
    ]
    checks.append(
        _check(
            "ordinary_chunks_within_max_tokens",
            "Every non-atomic-overflow chunk respects max_tokens",
            not oversized_unflagged,
            Severity.CRITICAL,
            gate=True,
            summary="All ordinary chunks fit."
            if not oversized_unflagged
            else f"{len(oversized_unflagged)} unflagged oversized chunk(s).",
            evidence={"chunk_ids": oversized_unflagged[:20], "max_tokens": config.max_tokens},
            remediation="An oversized chunk not marked is_atomic_overflow means a refinement stage failed to split or flag it.",
        )
    )

    atomic = [c for c in chunks if c.is_atomic_overflow]
    unpermitted_overflow = atomic if not config.allowed_atomic_overflow else []
    checks.append(
        _check(
            "atomic_overflow_requires_permission",
            "Atomic-overflow chunks are permitted by configuration",
            not unpermitted_overflow,
            Severity.CRITICAL,
            gate=True,
            summary=(
                f"{len(atomic)} atomic-overflow chunk(s), permitted by allowed_atomic_overflow=true."
                if config.allowed_atomic_overflow
                else (
                    "No atomic-overflow chunks."
                    if not atomic
                    else f"{len(atomic)} atomic-overflow chunk(s) present but allowed_atomic_overflow=false."
                )
            ),
            evidence={"atomic_overflow_chunk_ids": [c.chunk_id for c in atomic][:20]},
            remediation="Set allowed_atomic_overflow=true, or investigate why an unsplittable unit exceeds max_tokens.",
        )
    )

    # --- navigation / linking --------------------------------------------------
    nav_problems = []
    for i, c in enumerate(chunks):
        expected_prev = chunks[i - 1].chunk_id if i > 0 else None
        expected_next = chunks[i + 1].chunk_id if i < len(chunks) - 1 else None
        if c.previous_chunk_id != expected_prev or c.next_chunk_id != expected_next:
            nav_problems.append(c.chunk_id)
    checks.append(
        _check(
            "navigation_links_consistent",
            "previous/next links match document order",
            not nav_problems,
            Severity.CRITICAL,
            gate=True,
            summary="Navigation links consistent."
            if not nav_problems
            else f"{len(nav_problems)} inconsistent link(s).",
            evidence={"chunk_ids": nav_problems[:20]},
        )
    )

    parent_format_bad = [
        c.chunk_id
        for c in chunks
        if c.parent_chunk_id is not None and not c.parent_chunk_id.startswith("chunk_")
    ]
    checks.append(
        _check(
            "parent_chunk_id_well_formed",
            "parent_chunk_id, where set, is a well-formed chunk identifier",
            not parent_format_bad,
            Severity.CRITICAL,
            gate=True,
            summary="All set parent_chunk_id values are well-formed."
            if not parent_format_bad
            else f"{len(parent_format_bad)} malformed value(s).",
            evidence={"chunk_ids": parent_format_bad[:20]},
            remediation="parent_chunk_id is a deterministic lineage marker (the ID the pre-split chunk "
            "would have carried), not necessarily a foreign key to another row in this file — see "
            "docs/chunker/OUTPUT_SCHEMA.md.",
        )
    )

    # --- page/provenance ---------------------------------------------------
    max_page = len(doc.pages)
    bad_pages = [c.chunk_id for c in chunks if any(p < 1 or p > max_page for p in c.page_numbers)]
    checks.append(
        _check(
            "page_numbers_within_document_range",
            f"All page numbers are within [1, {max_page}]",
            not bad_pages,
            Severity.CRITICAL,
            gate=True,
            summary="All page numbers in range."
            if not bad_pages
            else f"{len(bad_pages)} chunk(s) with an out-of-range page number.",
            evidence={"chunk_ids": bad_pages[:20], "document_page_count": max_page},
        )
    )

    identity_mismatches = [
        c.chunk_id for c in chunks if c.source_sha256 != source_sha256 or c.document_id != document_id
    ]
    checks.append(
        _check(
            "source_identity_traceable",
            "Every chunk traces back to the same source SHA-256/document_id",
            not identity_mismatches,
            Severity.CRITICAL,
            gate=True,
            summary="Source identity consistent across all chunks."
            if not identity_mismatches
            else f"{len(identity_mismatches)} mismatch(es).",
            evidence={"chunk_ids": identity_mismatches[:20]},
        )
    )

    # --- table integrity -----------------------------------------------------
    table_fragments = [
        c
        for c in chunks
        if c.content_type is ContentType.TABLE and c.table_metadata and c.table_metadata.is_fragment
    ]
    unheadered = [
        c.chunk_id
        for c in table_fragments
        if config.repeat_table_headers and c.table_metadata and not c.table_metadata.header_repeated
    ]
    checks.append(
        _check(
            "table_fragments_carry_headers",
            "Table row-group fragments carry their column headers when configured",
            not unheadered,
            Severity.WARNING,
            gate=False,
            summary="All table fragments carry headers."
            if not unheadered
            else f"{len(unheadered)} fragment(s) missing headers.",
            evidence={"chunk_ids": unheadered[:20]},
        )
    )

    # --- overlap bounds --------------------------------------------------------
    overlap_violations = [
        c.chunk_id
        for c in chunks
        if c.was_recursively_split and c.overlap_tokens_before > config.text_overlap_tokens
    ]
    checks.append(
        _check(
            "overlap_within_configured_bounds",
            "Recursive-split overlap never exceeds text_overlap_tokens",
            not overlap_violations,
            Severity.WARNING,
            gate=False,
            summary="Overlap within bounds."
            if not overlap_violations
            else f"{len(overlap_violations)} violation(s).",
            evidence={"chunk_ids": overlap_violations[:20], "configured_overlap": config.text_overlap_tokens},
        )
    )

    # --- duplicate content (non-fragment) --------------------------------------
    text_counts: dict[str, list[str]] = {}
    for c in chunks:
        if (
            c.content_type in (ContentType.TABLE, ContentType.LIST, ContentType.CODE)
            and c.table_metadata
            and c.table_metadata.is_fragment
        ):
            continue
        text_counts.setdefault(c.text, []).append(c.chunk_id)
    unexpected_duplicates = {t: ids for t, ids in text_counts.items() if len(ids) > 1 and t.strip()}
    checks.append(
        _check(
            "no_unexpected_duplicate_content",
            "No two non-fragment chunks share identical text",
            not unexpected_duplicates,
            Severity.WARNING,
            gate=False,
            summary="No unexpected duplicate content."
            if not unexpected_duplicates
            else f"{len(unexpected_duplicates)} duplicated text group(s).",
            evidence={"examples": list(unexpected_duplicates.values())[:5]},
        )
    )

    # --- output file hygiene (only when a written file is supplied) -----------
    if chunks_jsonl_path is not None and chunks_jsonl_path.is_file():
        raw = chunks_jsonl_path.read_bytes()
        utf8_ok = True
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            utf8_ok = False
        lines = [line for line in raw.decode("utf-8", errors="replace").split("\n") if line.strip()]
        jsonl_ok = len(lines) == len(chunks)
        checks.append(
            _check(
                "jsonl_output_valid",
                "chunks.jsonl is valid UTF-8 with one JSON object per line",
                utf8_ok and jsonl_ok,
                Severity.CRITICAL,
                gate=True,
                summary="Valid UTF-8 JSONL."
                if utf8_ok and jsonl_ok
                else f"utf8_ok={utf8_ok}, line_count={len(lines)} vs {len(chunks)} chunks.",
            )
        )
        abs_path_hits = [
            c.chunk_id for c in chunks if c.figure_asset_path and (Path(c.figure_asset_path).is_absolute())
        ]
        checks.append(
            _check(
                "no_absolute_paths",
                "No chunk carries a machine-specific absolute path",
                not abs_path_hits,
                Severity.CRITICAL,
                gate=True,
                summary="No absolute paths."
                if not abs_path_hits
                else f"{len(abs_path_hits)} chunk(s) with an absolute asset path.",
                evidence={"chunk_ids": abs_path_hits[:20]},
            )
        )

    # --- human review items -----------------------------------------------------
    unreviewed_figures = [c.chunk_id for c in chunks if c.content_type is ContentType.FIGURE and c.warnings]
    if unreviewed_figures:
        human_review.append(
            f"{len(unreviewed_figures)} figure chunk(s) have no caption or generated description and "
            f"require human visual review: {unreviewed_figures[:10]}"
        )
    flagged_tables = [
        c.chunk_id
        for c in chunks
        if c.content_type in (ContentType.TABLE, ContentType.FIGURE)
        and c.parser_warnings
        and any("table" in w.lower() for w in c.parser_warnings)
    ]
    if flagged_tables:
        human_review.append(
            f"{len(flagged_tables)} chunk(s) carry parser warnings about unrecovered/raster table content "
            f"(including tables represented only as a picture region) and require human transcription "
            f"review: {flagged_tables[:10]}"
        )

    report = ChunkValidationReport(
        status=RunStatus.FAIL,  # replaced below; never default to success
        strict=config.strict,
        generated_at_utc=datetime.now(timezone.utc),
        checks=checks,
        human_review_items=human_review,
    )
    report.status = report.compute_status(config.strict)
    return report

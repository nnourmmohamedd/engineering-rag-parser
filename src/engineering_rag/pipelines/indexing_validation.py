"""Indexing pipeline validation gates.

Mirrors ``services/chunker/validation.py``'s gate pattern: hard failures
(``CRITICAL``, block the run / force ``FAIL``), acceptable warnings
(``WARNING``, downgrade status unless ``--strict``), and human-review items.
Combines chunk-run-level checks (tokenizer compatibility, schema), storage
checks (round-trip, self-retrieval, collection identity) and manifest
consistency checks in one report, following the numbered gate list recorded
in the milestone brief and ``docs/indexing/VALIDATION.md`` (added separately).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from engineering_rag.databases.chroma.validation import round_trip_check, self_retrieval_check
from engineering_rag.pipelines.indexing_models import (
    IndexRunStatus,
    IndexSeverity,
    IndexValidationCheck,
    IndexValidationReport,
)

__all__ = ["build_validation_report"]


def _check(
    check_id: str,
    title: str,
    passed: bool,
    severity: IndexSeverity,
    *,
    gate: bool,
    summary: str,
    evidence: dict[str, Any] | None = None,
    remediation: str = "",
) -> IndexValidationCheck:
    return IndexValidationCheck(
        check_id=check_id,
        title=title,
        passed=passed,
        severity=severity,
        gate=gate,
        summary=summary,
        evidence=evidence or {},
        remediation=remediation,
    )


def build_validation_report(  # noqa: PLR0915 - a flat gate list is clearer than artificial splitting
    *,
    chunk_records: list[dict[str, Any]],
    chunker_validation_status: str,
    tokenizer_family_ok: bool,
    tokenizer_family_summary: str,
    oversized_chunk_ids: list[str],
    max_seq_length: int,
    expected_ids: list[str],
    inserted_ids: list[str],
    existing_identical_ids: list[str],
    rejected_ids: list[str],
    collection_count: int,
    collection: Any,  # chromadb.Collection
    vector_problems: list[str],
    distance_metric_stored: str,
    expected_distance_metric: str,
    round_trip_ids: list[str],
    retrieval_texts_by_id: dict[str, str],
    self_retrieval_sample_ids: list[str],
    vectors_by_id: dict[str, list[float]],
    norm_tolerance: float,
    chunks_jsonl_path_is_relative: bool,
    strict: bool,
) -> IndexValidationReport:
    checks: list[IndexValidationCheck] = []
    human_review: list[str] = []

    # 1. chunks.jsonl valid & schema supported
    schema_versions = {r.get("schema_version") for r in chunk_records}
    checks.append(
        _check(
            "chunks_schema_supported",
            "chunks.jsonl has a recognized, uniform schema_version",
            len(schema_versions) <= 1 and bool(chunk_records),
            IndexSeverity.CRITICAL,
            gate=True,
            summary=f"schema_version(s) seen: {sorted(str(v) for v in schema_versions)}",
            evidence={"schema_versions": sorted(str(v) for v in schema_versions)},
        )
    )

    # 2. chunker run passed validation
    checks.append(
        _check(
            "chunker_run_passed_validation",
            "The source chunker run's own validation_report.json status is PASS or PASS_WITH_WARNINGS",
            chunker_validation_status in ("PASS", "PASS_WITH_WARNINGS"),
            IndexSeverity.CRITICAL,
            gate=True,
            summary=f"Chunker run status: {chunker_validation_status}",
            evidence={"chunker_status": chunker_validation_status},
            remediation="Re-run the chunker until it passes before indexing its output.",
        )
    )

    # 3. tokenizer matches BGE family (hard reject)
    checks.append(
        _check(
            "tokenizer_family_match",
            "Chunk run's tokenizer matches the embedding model's tokenizer family",
            tokenizer_family_ok,
            IndexSeverity.CRITICAL,
            gate=True,
            summary=tokenizer_family_summary,
            remediation="Re-run the chunker with a tokenizer matching the embedding model "
            "(see configs/chunker_bge.yaml) before indexing.",
        )
    )

    # 4. no silent truncation (recomputed with the real embedding tokenizer)
    checks.append(
        _check(
            "no_silent_truncation",
            f"Every retrieval_text is <= {max_seq_length} tokens under the embedding model's own tokenizer",
            not oversized_chunk_ids,
            IndexSeverity.CRITICAL,
            gate=True,
            summary="No oversized chunks."
            if not oversized_chunk_ids
            else f"{len(oversized_chunk_ids)} chunk(s) exceed {max_seq_length} tokens and would be silently truncated.",
            evidence={"chunk_ids": oversized_chunk_ids[:20]},
            remediation="Lower chunker target_tokens/max_tokens, or raise the embedding model's sequence length.",
        )
    )

    # 5. every expected chunk_id represented
    missing_ids = sorted(set(expected_ids) - set(inserted_ids) - set(existing_identical_ids))
    checks.append(
        _check(
            "all_expected_ids_present",
            "Every chunk_id in chunks.jsonl is represented in the collection",
            not missing_ids,
            IndexSeverity.CRITICAL,
            gate=True,
            summary="All expected ids present." if not missing_ids else f"{len(missing_ids)} missing id(s).",
            evidence={"missing_ids": missing_ids[:20]},
        )
    )

    # 6. no unexpected/duplicate IDs
    duplicate_expected = [i for i in expected_ids if expected_ids.count(i) > 1]
    checks.append(
        _check(
            "no_duplicate_or_unexpected_ids",
            "No duplicate chunk_id in the input and no rejected-id conflicts",
            not duplicate_expected and not rejected_ids,
            IndexSeverity.CRITICAL,
            gate=True,
            summary="No duplicates/rejections."
            if not duplicate_expected and not rejected_ids
            else "Problems found.",
            evidence={
                "duplicate_ids": sorted(set(duplicate_expected))[:20],
                "rejected_ids": rejected_ids[:20],
            },
        )
    )

    # 7. correct collection count
    expected_count_floor = len(set(expected_ids))
    checks.append(
        _check(
            "collection_count_covers_input",
            "Collection count is at least the number of unique input chunk ids",
            collection_count >= expected_count_floor,
            IndexSeverity.CRITICAL,
            gate=True,
            summary=f"Collection count {collection_count} vs {expected_count_floor} expected unique id(s).",
            evidence={"collection_count": collection_count, "expected_minimum": expected_count_floor},
        )
    )

    # 8. every vector 768-d, finite, nonzero, normalized
    checks.append(
        _check(
            "vectors_valid",
            "Every embedded vector is well-formed (dimension, finite, nonzero, normalized)",
            not vector_problems,
            IndexSeverity.CRITICAL,
            gate=True,
            summary="All vectors valid." if not vector_problems else f"{len(vector_problems)} problem(s).",
            evidence={"problems": vector_problems[:20]},
        )
    )

    # 9. Chroma uses cosine
    checks.append(
        _check(
            "cosine_distance_metric",
            "Collection is configured with cosine distance",
            distance_metric_stored == expected_distance_metric == "cosine",
            IndexSeverity.CRITICAL,
            gate=True,
            summary=f"Stored metric: {distance_metric_stored!r}",
            evidence={"stored": distance_metric_stored, "expected": expected_distance_metric},
        )
    )

    # 10 & 11. round trip: stored documents equal retrieval_text + metadata round-trips
    round_trip_problems = round_trip_check(
        collection,
        ids=round_trip_ids,
        expected_documents=retrieval_texts_by_id,
        norm_tolerance=norm_tolerance,
    )
    checks.append(
        _check(
            "round_trip_storage_matches",
            "Sampled round-trip fetch: stored document equals retrieval_text, vector re-normalizes",
            not round_trip_problems,
            IndexSeverity.CRITICAL,
            gate=True,
            summary="Round-trip storage verified."
            if not round_trip_problems
            else f"{len(round_trip_problems)} problem(s).",
            evidence={"problems": round_trip_problems[:20]},
        )
    )

    # 12. self-retrieval integrity
    self_retrieval_failures = self_retrieval_check(
        collection, sample_ids=self_retrieval_sample_ids, vectors_by_id=vectors_by_id
    )
    checks.append(
        _check(
            "self_retrieval_rank_one",
            "Each sampled chunk's own vector retrieves that chunk at rank 1",
            not self_retrieval_failures,
            IndexSeverity.WARNING,
            gate=False,
            summary="All sampled chunks self-retrieve at rank 1."
            if not self_retrieval_failures
            else f"{len(self_retrieval_failures)} failure(s) (may indicate exact-vector ties).",
            evidence={"failures": self_retrieval_failures[:20]},
        )
    )

    # 13. output path portability
    checks.append(
        _check(
            "relative_paths_portable",
            "Manifest paths are recorded relative (portable across machines)",
            chunks_jsonl_path_is_relative,
            IndexSeverity.WARNING,
            gate=False,
            summary="Paths are relative."
            if chunks_jsonl_path_is_relative
            else "An absolute path was recorded.",
        )
    )

    if missing_ids:
        human_review.append(
            f"{len(missing_ids)} chunk(s) failed to index and need investigation: {missing_ids[:10]}"
        )

    report = IndexValidationReport(
        status=IndexRunStatus.FAIL,
        strict=strict,
        generated_at_utc=datetime.now(timezone.utc),
        checks=checks,
        human_review_items=human_review,
    )
    report.status = report.compute_status(strict)
    return report

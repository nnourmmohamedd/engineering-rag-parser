# Chunker Validation

`services/chunker/validation.py` runs every gate below against a finished
chunk list and writes `validation_report.json`. Status logic
(`ChunkValidationReport.compute_status`) mirrors the parser's own: any failed
`CRITICAL` check forces `FAIL`; a failed `WARNING` check (with nothing
`CRITICAL` failed) yields `PASS_WITH_WARNINGS` (or `FAIL` under `--strict`).
**`PASS_WITH_WARNINGS` never hides a failed hard gate** — a run with both a
critical failure and warnings reports `FAIL`.

## Hard gates (`CRITICAL`, `gate: true`)

| `check_id` | What it proves |
|---|---|
| `no_empty_chunks` | Every chunk's `text` is non-empty after stripping |
| `no_duplicate_chunk_ids` | No two chunks share a `chunk_id` |
| `deterministic_ids_recomputable` | Every `chunk_id` recomputes correctly from `(document_id, chunk_index, text)` |
| `ordinary_chunks_within_max_tokens` | Every chunk over `max_tokens` is explicitly flagged `is_atomic_overflow` |
| `atomic_overflow_requires_permission` | Any `is_atomic_overflow` chunk is only present when `allowed_atomic_overflow: true` |
| `navigation_links_consistent` | `previous_chunk_id`/`next_chunk_id` form a correct chain matching document order |
| `parent_chunk_id_well_formed` | A set `parent_chunk_id` is a well-formed identifier (see `OUTPUT_SCHEMA.md` on why this checks format, not row-resolution) |
| `page_numbers_within_document_range` | Every `page_numbers` entry is within `[1, len(doc.pages)]` |
| `source_identity_traceable` | Every chunk's `source_sha256`/`document_id` matches the run's actual source |
| `jsonl_output_valid` | `chunks.jsonl` is valid UTF-8 with exactly one JSON object per line (checked against the file actually written to disk, not the in-memory objects) |
| `no_absolute_paths` | No chunk's `figure_asset_path` is an absolute, machine-specific path |

## Warnings (`WARNING`, `gate: false`)

| `check_id` | What it proves |
|---|---|
| `table_fragments_carry_headers` | Every table row-group fragment carries its header when `repeat_table_headers: true` |
| `overlap_within_configured_bounds` | No recursive-split chunk's recorded overlap exceeds `text_overlap_tokens` |
| `no_unexpected_duplicate_content` | No two non-fragment chunks share byte-identical `text` |

## Human-review items (informational, never a gate)

- Every FIGURE chunk with no caption/generated description is listed —
  visual content is not represented in text and requires human confirmation
  (mirrors the parser's own figure-review requirement).
- Every TABLE or FIGURE chunk carrying a `parser_warnings` entry that
  mentions "table" (an unrecovered/raster table, including one Docling
  represented only as a picture region) is listed for human transcription
  review.

## What is verified by tests instead of a runtime gate

Some spec requirements are properties of *repeated execution*, not of one
run's output in isolation, and are covered by dedicated tests rather than a
`validation_report.json` gate:

- **Deterministic output across two identical runs** —
  `tests/integration/pipelines/test_chunking_acceptance.py::TestDeterministicRepeatedRuns`
  (real engineering PDF) and
  `tests/integration/services/chunker/test_service_pipeline.py::test_repeated_runs_produce_byte_identical_chunks_jsonl`
  (synthetic fixture) both byte-compare two runs' `chunks.jsonl`.
- **Manifest hashes match generated files** —
  `test_manifest_hashes_match_generated_files` recomputes SHA-256 of
  `chunks.jsonl`/`validation_report.json` and compares against
  `manifest.json`'s recorded hashes.
- **No row lost across table fragments** —
  `tests/unit/services/chunker/test_type_handlers.py::TestTableRefinement::test_no_row_lost_across_fragments`
  asserts every row's tag text survives somewhere in the fragment set.
- **Recursive children preserve heading path / stay within bounds /
  deterministic ordering** — `test_recursive.py`.

## Severity/gate summary at a glance

```text
CRITICAL, gate=True   -> 11 checks (any failure => FAIL)
WARNING,  gate=False  ->  3 checks (failure => PASS_WITH_WARNINGS, or FAIL under --strict)
INFO (human review)   -> figure/table review items, never affects status
```

# Chunker Output Schema

`schema_version` (currently `"1.0.0"`, `CHUNK_SCHEMA_VERSION` in
`services/chunker/models.py`) is written on every chunk record so a future
consumer can detect a schema change before parsing fails confusingly.

## `chunks.jsonl`

One JSON object per line, UTF-8, LF line endings, no trailing commas, written
atomically (temp file + rename — an interrupted run never leaves a
partially-written `chunks.jsonl` that looks valid). Fields:

| Field | Type | Always present? | Meaning |
|---|---|---|---|
| `schema_version` | str | yes | Output contract version |
| `chunk_id` | str | yes | Stable, deterministic (`chunk_<16 hex chars>`) — see below |
| `document_id` | str | yes | The source PDF's own SHA-256 (unchanged across runs/config) |
| `source_filename` | str | yes | Original PDF filename |
| `source_sha256` | str | yes | Same value as `document_id`, kept as a separate explicit field for clarity |
| `chunk_index` | int | yes | 0-based position in final document order |
| `content_type` | enum | yes | `text` \| `table` \| `list` \| `code` \| `equation` \| `figure` |
| `text` | str | yes | **Faithful content only — never invents facts** |
| `retrieval_text` | str | yes | `text`, optionally prefixed with heading/caption context (see below) |
| `token_count` | int | yes | Measured by `tokenizer_name`, over `retrieval_text`... *(see note)* |
| `tokenizer_name` | str | yes | e.g. `sentence-transformers/all-MiniLM-L6-v2` |
| `heading_path` | list[str] | yes (`[]` if none) | Document title → section → subsection |
| `section_title` | str\|null | | Last element of `heading_path`, or null |
| `captions` | list[str] | yes (`[]`) | Docling-linked captions, when present |
| `labels` | list[str] | yes (`[]`) | Underlying Docling `DocItemLabel` value(s) |
| `page_numbers` | list[int] | yes (`[]`) | 1-based, sorted, deduplicated |
| `provenance` | list[object] | yes (`[]`) | `{page_no, bbox: [l,t,r,b]|null, charspan: [start,end]|null}` |
| `source_element_refs` | list[str] | yes (`[]`) | Docling `self_ref` value(s) this chunk was built from |
| `parent_chunk_id` | str\|null | | See "Lineage" below |
| `previous_chunk_id` / `next_chunk_id` | str\|null | | Document-order navigation |
| `merged_from_chunk_ids` | list[str]\|null | | See "Lineage" below |
| `split_method` | enum | yes | `hierarchical` \| `recursive_text` \| `table_rows` \| `list_items` \| `code_block` \| `equation_atomic` \| `figure` \| `merged` |
| `was_recursively_split` | bool | yes | True only for `recursive_text` children |
| `overlap_tokens_before` | int | yes (`0`) | Token overlap with the previous sibling (recursive text only) |
| `table_metadata` | object\|null | | `{num_rows, num_cols, is_fragment, fragment_index, total_fragments, header_repeated, detected_label}` |
| `figure_asset_path` | str\|null | | Relative path (portable, no absolute paths — see the parser's own convention) |
| `figure_page_no` | int\|null | | |
| `is_atomic_overflow` | bool | yes | True when this chunk exceeds `max_tokens` as an explicitly-permitted, unsplittable unit |
| `parser_warnings` | list[str] | yes (`[]`) | Propagated verbatim from the parser's own `validation/report.json` findings for the underlying element(s) |
| `warnings` | list[str] | yes (`[]`) | Chunk-level warnings generated during chunking itself |

*Note on `token_count`:* measured over the same text passed to the tokenizer
during size-budget decisions — for hierarchical/type-handler-produced chunks
this is `text`; `retrieval_text` is typically `text` plus a short heading/
caption prefix, so `retrieval_text`'s true token count is usually slightly
higher than `token_count`. This is a known, documented approximation: adding
heading context is a small, bounded addition (a handful of tokens), and
re-measuring after every prefix decision would complicate the pipeline for
negligible benefit. If your embedding model's hard limit is very close to
`max_tokens`, lower `max_tokens` slightly to leave headroom (see
`CONFIGURATION.md`).

## `text` vs. `retrieval_text`

- **`text`** is the chunk's faithful content, taken directly from the source
  document (or a deterministic row/line/item regrouping of it). It never has
  anything added.
- **`retrieval_text`** is what an embedding step would encode: `text`,
  optionally prefixed with `heading_path`/`captions` (when
  `include_heading_context: true`), joined with `\n`. This adds *context that
  already exists in the document* — it never invents a fact, a number, or a
  relationship not present in `text` or the heading/caption metadata.

## Chunk ID stability

`chunk_id = "chunk_" + sha256(f"{document_id}|{chunk_index}|{text}")[:16]`
(`services/chunker/ids.py`). No randomness (no UUIDs) anywhere: identical
input + identical configuration always produces identical IDs, and therefore
a byte-identical `chunks.jsonl` — verified by
`tests/integration/pipelines/test_chunking_acceptance.py::TestDeterministicRepeatedRuns`
on the real engineering PDF.

## Lineage: `parent_chunk_id` and `merged_from_chunk_ids`

Both are **deterministic lineage markers**, not foreign keys into other rows
of the same `chunks.jsonl`:

- `parent_chunk_id`: when a hierarchical chunk was too large and got split
  into several output chunks, this is the ID that pre-split chunk *would
  have* carried, had it shipped whole (computed from its position before
  splitting and its own un-split text). It never appears as a row on its own.
- `merged_from_chunk_ids`: the (pre-merge) IDs of the chunks that were
  combined into this one, computed the same way, from their position and
  text before merging.

This design was chosen so that lineage is fully computable from
`(document_id, index, text)` alone — auditable and reproducible without a
separate lookup table — at the cost of these IDs not literally resolving to
another JSONL line. `validation.py`'s `parent_chunk_id_well_formed` gate
checks the *format* of a set `parent_chunk_id`, not that it resolves to a row.

## `manifest.json`

Source identity, `config_hash`, effective configuration, tokenizer, per-stage
timings, content-type counts, token statistics (min/median/mean/p95/max),
recursively-split and merged counts, chunk-level warnings, output artifact
SHA-256 hashes, software versions, final status.

## `validation_report.json`

See `VALIDATION.md` for the full gate list; format mirrors the parser's own
`ValidationReport` (checks with `severity`/`gate`/`evidence`/`remediation`,
plus `human_review_items`).

## `chunking_summary.md`

Human-readable run summary: configuration, statistics, the validation table,
warnings, human-review items, timings.

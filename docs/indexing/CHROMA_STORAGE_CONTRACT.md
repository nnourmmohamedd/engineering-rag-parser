# Chroma Storage Contract

`chunks.jsonl` (produced by the chunker) remains the single canonical
provenance record. ChromaDB is the *searchable index*, not a second source
of truth — every stored vector is traceable back to its full canonical chunk
record via `chunk_id` and `source: chunk_run_id` in its metadata.

## Client and persistence

- `databases/chroma/client.py::get_client()` opens a `chromadb.PersistentClient`
  rooted at `chroma.persistence_path` (default `data/output/databases/chroma`,
  configurable, stable across runs — **not** per-run, unlike the parser/chunker
  output directories, because a Chroma collection accumulates across many
  indexing runs by design).
- Telemetry is disabled (`chromadb.config.Settings(anonymized_telemetry=False)`)
  by default via `chroma.telemetry: false`.
- No remote/anonymous Chroma server is ever used — always local persistence.

## Collection identity and compatibility

Every collection is created with identity metadata
(`databases/chroma/models.py::CollectionIdentity`):

| Metadata key | Meaning |
|---|---|
| `model_name` | Embedding model that produced the vectors in this collection |
| `embedding_dimension` | Fixed at 768 for the production profile |
| `distance_metric` | `cosine` (also set as Chroma's own `hnsw:space`) |
| `tokenizer_name` | Must match `model_name` (see `VALIDATION.md` gate 3) |
| `corpus_id` | First 16 hex chars of the indexing config's `config_hash()` |
| `index_schema_version` | `"1.0.0"` |

`databases/chroma/collection.py::open_or_create_collection()` compares this
identity against an existing collection's stored metadata on every open; any
disagreement is a hard `CollectionMismatchError` — a collection is never
silently reused across an incompatible model, dimension, metric, or schema
change. Destructive replacement is only possible via
`rebuild_collection()`, gated behind `chroma.allow_rebuild: true` in the
profile **and** the CLI's explicit `--rebuild` flag; the exact collection
name and path are printed before the delete happens.

## Per-chunk storage

| Chroma field | Source |
|---|---|
| `id` | `chunk_id` (stable, deterministic — see chunker's `OUTPUT_SCHEMA.md`) |
| `embedding` | Normalized 768-d BGE vector |
| `document` | `retrieval_text` |
| `metadata` | see below |

Metadata (`pipelines/indexing_pipeline.py::_build_metadata`, encoded through
`databases/chroma/metadata.py::chroma_safe_metadata()`):

`document_id`, `source_filename`, `source_sha256`, `chunk_index`,
`content_type`, `section_title`, `heading_path` (JSON-encoded string —
Chroma has no native list type), `page_numbers` (JSON-encoded string),
`source_element_refs` (JSON-encoded string, capped at 4000 characters —
larger values are truncated with a `...(truncated)"` marker so a consumer can
detect it; the full untruncated list always remains available in
`chunks.jsonl`), `parent_chunk_id`, `previous_chunk_id`, `next_chunk_id`
(omitted, not stored as `None`, when absent — see below), `chunk_schema_version`,
`tokenizer_name` (the *embedding* model's tokenizer, not the chunker's),
`token_count` (recomputed with the embedding model's own tokenizer — never
the chunker's stored count, which was measured for a different tokenizer;
see `VALIDATION.md` gate 4), `chunk_run_id`, `index_schema_version`,
`warnings_summary` (a short joined string, capped at 200 characters — the
full list stays in `chunks.jsonl`), and `content_hash` (used for idempotency,
see below).

### Chroma metadata compatibility

Confirmed by direct introspection of the installed chromadb 1.5.9, not
assumed from documentation that may describe an older version: metadata
values must be `str | int | float | bool` — passing `None` raises
`TypeError: Cannot convert Python object to MetadataValue`. `chroma_safe_metadata()`
is the single place this is handled: `None`/empty values are **omitted**
(the key is simply absent from the record) rather than sent as `None`, and
lists/dicts are JSON-encoded as compact strings.

## Idempotency and safety

Reindexing identical input must never duplicate. The rule
(`databases/chroma/repository.py::ingest_batch`):

1. Compute `content_hash(retrieval_text, metadata)` — a stable SHA-256 over
   the passage text plus its own metadata fields — and store it as the
   `content_hash` metadata field on every record.
2. On write, fetch any existing records at the same `id`s first.
3. Same `id`, same `content_hash` already stored → **skip** (idempotent
   no-op, counted as `existing_identical`).
4. Same `id`, **different** `content_hash` → hard failure
   (`DuplicateIdConflictError`) — never a silent overwrite.
5. `id` not present at all → inserted via `collection.upsert()`.

Batches are written via `chroma.ingestion_batch_size`; after all batches, the
full collection is re-validated (`pipelines/indexing_validation.py`) and only
then is `index_manifest.json` written with `status: PASS` — an interrupted
run leaves no manifest, so it can never be mistaken for a completed,
READY index. No collection is ever deleted automatically.

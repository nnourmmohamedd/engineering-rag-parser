# Indexing Validation Gates

`pipelines/indexing_validation.py::build_validation_report()` produces one
`IndexValidationReport` per run, mirroring the chunker's gate pattern: every
check carries `severity` (`CRITICAL` / `WARNING`), `gate` (whether it can
force `FAIL`), `summary`, `evidence`. `PASS_WITH_WARNINGS` never hides a
failed `CRITICAL`/`gate=true` check — `IndexValidationReport.compute_status()`
returns `FAIL` if *any* gate check failed, regardless of warnings.

## Admission checks (run before any Chroma write — `IndexingInputError` if failed)

These happen in `pipelines/indexing_pipeline.py::_admission_check()`, before
a run directory even exists, so a rejected input leaves no partial artifacts:

1. **`chunks.jsonl` is valid / schema supported** — a single, consistent
   `schema_version` across all records.
2. **The source chunker run passed its own validation** —
   `validation_report.json`'s `status` must be `PASS` or `PASS_WITH_WARNINGS`.
3. **Tokenizer match (hard reject)** — the chunk run's recorded
   `tokenizer.name` (from the chunker's `manifest.json`) must be **exactly
   equal** to `embedding.model_name`. Deliberately strict equality, not a
   fuzzy "family" match: different tokenizers count tokens differently, so
   only exact equality guarantees the chunker's size-budget decisions are
   meaningful for this embedding model's own limits.
4. **No silent truncation** — every `retrieval_text` is independently
   re-measured with the *embedding* model's own tokenizer (never the
   chunker's stored `token_count`, which was measured for the chunker's
   sizing purposes under a possibly different tokenizer). Any chunk
   exceeding `maximum_sequence_length` under this recount is a hard
   admission failure, not a truncation.

## Storage/report gates (recorded in `index_validation_report.json`)

| # | `check_id` | Severity | What it proves |
|---|---|---|---|
| 5 | `chunks_schema_supported` | CRITICAL (gate) | Restated in the report for auditability |
| 6 | `chunker_run_passed_validation` | CRITICAL (gate) | Restated in the report |
| 7 | `tokenizer_family_match` | CRITICAL (gate) | Restated in the report |
| 8 | `no_silent_truncation` | CRITICAL (gate) | Restated in the report |
| 9 | `all_expected_ids_present` | CRITICAL (gate) | Every `chunk_id` in `chunks.jsonl` is either newly inserted or already-identical in the collection — none missing |
| 10 | `no_duplicate_or_unexpected_ids` | CRITICAL (gate) | No duplicate `chunk_id` in the input; no id was rejected due to a conflicting content hash |
| 11 | `collection_count_covers_input` | CRITICAL (gate) | `collection.count()` is at least the number of unique input ids (accounts for prior runs sharing the collection) |
| 12 | `vectors_valid` | CRITICAL (gate) | Every embedded vector is 768-d, finite, non-zero, normalized within tolerance — enforced per-vector at embed time (`services/embedder/validation.py::validate_vector`), restated here |
| 13 | `cosine_distance_metric` | CRITICAL (gate) | The collection's stored `hnsw:space`/`distance_metric` metadata is `cosine` |
| 14 | `round_trip_storage_matches` | CRITICAL (gate) | A sampled fetch confirms the stored `document` equals `retrieval_text` and the stored vector re-normalizes |
| 15 | `self_retrieval_rank_one` | WARNING (not a gate) | Querying Chroma with a sampled chunk's own stored vector returns that `chunk_id` at rank 1 — validates the storage/index round trip itself, not semantic retrieval quality. Not a hard gate because an exact-vector tie (two chunks with identical text) is a documented, legitimate outcome, not a defect. |
| 16 | `relative_paths_portable` | WARNING (not a gate) | The manifest's recorded chunk-input path is relative, not machine-specific absolute |

`READY`/`status: PASS` is only ever written after every `CRITICAL`/`gate=true`
check passes — an interrupted run (process killed mid-embedding, mid-ingestion,
or mid-validation) leaves no `index_manifest.json` at all, so it can never be
mistaken for a completed index.

## Additional guarantees verified elsewhere in the codebase (not separate `check_id`s)

- **Model/schema incompatibility rejected** — `databases/chroma/collection.py::open_or_create_collection()`
  raises `CollectionMismatchError` before any write if an existing
  collection's identity metadata disagrees with the current run.
- **Idempotent rerun** — `databases/chroma/repository.py::ingest_batch()`;
  verified by both unit tests and the real-document acceptance run (§ see
  `INDEXING_COMPLETION_REPORT.md`).
- **Manifest matches the physical collection** — `collection_count_after_run`
  in `index_manifest.json` is read directly from `collection.count()` at the
  end of the same run, not computed separately.
- **Database reopens in a fresh process** — `engrag-index inspect` opens a new
  `chromadb.PersistentClient` in a separate process invocation and reads the
  same collection; exercised in both integration tests and manual CLI
  verification (see `INDEXING_COMPLETION_REPORT.md`).
- **No secrets or model weights stored in the repository** — the Hugging
  Face cache lives outside the repo tree (the OS user cache directory); the
  Chroma persistence directory is git-ignored (`data/output/` is excluded,
  matching the parser/chunker convention).

## Semantic smoke tests (explicitly separate from hard gates)

`engrag-index smoke-query` is a diagnostic-only command. Its own CLI output
is prefixed `"DIAGNOSTIC smoke-query — not the final retrieval interface."`
Any semantic-quality observation made with it (e.g. "the top result for
'What is a control system?' was the Control Philosophy section") is an
automated lexical/embedding-similarity observation, not a human relevance
judgement, and is never used to compute `PASS`/`FAIL` status. Full retrieval
evaluation is explicitly the next milestone's scope.

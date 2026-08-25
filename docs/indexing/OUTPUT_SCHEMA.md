# Indexing Output Schema

Every completed indexing run writes four files into its own report directory
(`<output_root>/<collection_name>/<run_id>/`, e.g.
`data/output/indexing/engineering_documents_v1/20260825T081247Z-4eeb2768/`).
`schema_version` (`INDEX_MANIFEST_SCHEMA_VERSION = "1.0.0"`,
`pipelines/indexing_models.py`) is written into the manifest so a future
consumer can detect a schema change.

## `index_manifest.json` (`IndexManifest`)

| Field | Meaning |
|---|---|
| `schema_version` | Output contract version |
| `run_id` | This indexing run's timestamped ID |
| `generated_at_utc` | Run completion timestamp |
| `collection_name` / `chroma_path` | Where the vectors were written |
| `input_chunks_jsonl_path` / `input_chunks_jsonl_sha256` | Exact input file and its hash |
| `input_chunk_run_id` | The chunker run this index was built from |
| `source_documents` | `[{filename, sha256}]` from the chunker's own manifest |
| `chunk_count` / `content_type_counts` | What was processed |
| `model_name` / `resolved_model_revision` / `tokenizer_name` | Embedding model identity |
| `embedding_dimension` / `max_seq_length` / `normalize_embeddings` | Vector shape and normalization |
| `distance_metric` | Always `cosine` for this adapter |
| `query_prefix` / `document_prefix` | Recorded verbatim (not secrets) |
| `batch_size` / `device` | Runtime parameters actually used |
| `versions` | `sentence-transformers`, `chromadb`, `transformers`, `torch`, `numpy` versions |
| `collection_count_after_run` | Chroma's own `collection.count()` after this run |
| `vector_validation_stats` | `{validated_count, embedding_duration_s, vectors_per_second}` |
| `config_hash` | SHA-256 over the effective `IndexingConfig` |
| `status` | `PASS` \| `PASS_WITH_WARNINGS` \| `FAIL` — from the validation report |
| `warnings` | Short warning summaries |
| `timings_s` | `load_s`, `embedding_s`, `ingestion_s`, `validation_s` |

## `ingestion_report.json`

`{expected_ids, inserted_ids, existing_identical_ids, rejected_ids, final_count, errors}` —
the exact per-id outcome of `databases/chroma/repository.py::ingest_batch()`
across every batch of the run. No `updated_ids` field exists: this adapter
never updates a record under an unchanged id — see `CHROMA_STORAGE_CONTRACT.md`'s
idempotency rule (same id + same hash → skip; same id + different hash →
hard failure, not an update).

## `index_validation_report.json` (`IndexValidationReport`)

`{status, strict, generated_at_utc, checks: [IndexValidationCheck...], human_review_items}`.
Each `IndexValidationCheck` carries `check_id`, `title`, `passed`, `severity`
(`CRITICAL` \| `WARNING` \| `INFO`), `gate` (true for a hard acceptance gate),
`summary`, `evidence`, `remediation`. See `VALIDATION.md` for the full list
of gates and what "gate: true, severity: CRITICAL" vs. "gate: false,
severity: WARNING" means for the run's final status.

## `index_summary.md`

Human-readable: status, input, chunk-run ID, model + resolved revision,
tokenizer, embedding dimension, distance metric, collection name and Chroma
path, collection count after the run, duration, throughput, content-type
counts, failed-gate/warning counts, and the exact `engrag-index
inspect`/`validate` commands to reproduce the inspection.

## Chroma-stored record shape

See `CHROMA_STORAGE_CONTRACT.md` for the full per-chunk `id` /
`embedding` / `document` / `metadata` mapping — that document is the
authoritative schema for what actually lives inside the Chroma collection
itself, as opposed to the run-report files described above.

## No raw-vector export

This milestone does not implement a raw-vector JSON/NumPy export path.
`chunks.jsonl` (canonical provenance) plus the persistent Chroma collection
(the searchable index) together are the complete, non-duplicated record —
adding a third copy of the vectors was judged to add duplication risk
without a corresponding need at this milestone's scope.

# Indexing Configuration

`configs/indexing_production.yaml` is loaded by
`pipelines/indexing_config.py::load_indexing_config()`, which validates every
field **before** any embedding model is loaded or any Chroma client is
opened — a malformed profile fails fast with a clear pydantic error.

## `embedding:` (`services/embedder/config.py::EmbedderConfig`)

| Parameter | Default | Purpose | Consequence if changed |
|---|---|---|---|
| `model_name` | `BAAI/bge-base-en-v1.5` | SentenceTransformers model id | Changing this requires re-embedding the whole corpus and is a genuine product decision — see `EMBEDDING_MODEL_DECISION.md` |
| `model_revision` | `null` | Optional pinned commit for reproducibility | `null` resolves to the model's `main` ref at load time; pin for byte-for-byte reproducible deployments |
| `trust_remote_code` | `false` | Passed to `SentenceTransformer()` | Off by default for safety — do not enable without reviewing the model's remote code |
| `expected_dimension` | `768` | Output vector width this profile requires | A model producing a different dimension fails to load (`ModelLoadError`) rather than silently storing mismatched vectors |
| `maximum_sequence_length` | `512` | Used for the no-silent-truncation admission gate | Chunks measured (by the embedding model's own tokenizer) above this are rejected, not truncated |
| `normalize_embeddings` | `true` | L2-normalize every vector | Required for cosine distance to behave as expected; `false` is not a supported production configuration for this adapter |
| `batch_size` | `32` | Encode batch size | CPU-safe default; raise for GPU throughput, lower if memory-constrained |
| `device` | `auto` | `auto` \| `cpu` \| `cuda` | `auto` picks CUDA only if available and logs the resolved device |
| `document_field` | `retrieval_text` | Chunk JSONL field embedded as a passage | Must match the chunker's `OUTPUT_SCHEMA.md` field name |
| `document_prefix` | `""` (empty) | Prepended to passages | Must stay empty per the BGE model card — passages get no instruction prefix |
| `query_prefix` | `"Represent this sentence for searching relevant passages: "` | Prepended to queries only | The exact BGE-required instruction string; must not be empty (validated) |
| `offline` | `false` | Sets `HF_HUB_OFFLINE=1` | `true` requires the model already be cached locally, or loading fails with an actionable error |

## `chroma:` (`databases/chroma/config.py::ChromaConfig`)

| Parameter | Default | Purpose | Consequence if changed |
|---|---|---|---|
| `persistence_path` | `data/output/databases/chroma` | Base directory for the persistent client | Stable across runs (not per-run) — a collection accumulates here across many `build` invocations |
| `collection_name` | `engineering_documents_v1` | Chroma collection name | Must satisfy Chroma's own naming rules (3–512 chars, alnum start/end, no `..`, not an IPv4 literal) — validated at config-parse time |
| `distance_metric` | `cosine` | `hnsw:space` | Only `cosine` is supported by this adapter (a `Literal["cosine"]` field) |
| `ingestion_batch_size` | `100` | Records per `collection.upsert()` call | Larger batches trade memory for fewer round trips |
| `idempotent` | `true` | Same id + same content hash on rerun is a no-op | `false` downgrades a hash conflict from a hard failure to a rejected-and-reported id — not recommended in production |
| `allow_rebuild` | `false` | Whether `--rebuild` is permitted at all | Must be explicitly enabled in the profile **and** passed on the CLI before a destructive rebuild can happen |
| `telemetry` | `false` | Chroma's `anonymized_telemetry` setting | Off by default; this adapter never sends usage data anywhere |

## `validation:` (`pipelines/indexing_config.py::IndexValidationConfig`)

| Parameter | Default | Purpose |
|---|---|---|
| `norm_tolerance` | `0.001` | Allowed deviation of a vector's L2 norm from 1.0 |
| `require_all_chunks` | `true` | Every `chunk_id` must land in the collection |
| `require_round_trip_match` | `true` | Stored document/vector must match what was written (re-fetched and compared) |
| `require_model_tokenizer_match` | `true` | Reject ingestion if the chunk run's tokenizer does not match the embedding model — see `VALIDATION.md` gate 3 |
| `self_retrieval_sample_size` | `20` | Number of chunks sampled for the self-retrieval rank-1 integrity test |
| `fail_on_model_mismatch` | `true` | An existing collection with incompatible identity metadata is a hard failure |

## `logging:`

`log_level: INFO` — follows the existing centralized logging contract
(`engineering_rag.utils.logging`); no separate indexing-specific logging
mechanism was introduced.

## Top-level

`output_root` (default `data/output/indexing`) — base directory for per-run
report artifacts (distinct from `chroma.persistence_path`, which is the
stable Chroma database location itself). `strict` (default `false`) —
treat validation warnings as failures, matching the parser/chunker `--strict`
convention.

## Validation performed at parse time

Positive batch sizes (`gt=0` on every batch-size field); `expected_dimension`
fixed at `768` for this profile (both at the `EmbedderConfig` field level and
again as an `IndexingConfig`-level cross-check); `device` restricted to a
`Literal["auto", "cpu", "cuda"]`; non-empty `model_name` and `query_prefix`;
Chroma-legal `collection_name` (rejected before any database is touched);
`distance_metric` restricted to `Literal["cosine"]`. All of `EmbedderConfig`,
`ChromaConfig`, `IndexingConfig` are frozen pydantic models with
`extra="forbid"` — an unrecognized YAML key is a configuration error, not a
silently ignored typo.

# Chunker Configuration

Follows the parser's own YAML convention (`configs/*.yaml`): a public,
hashable, `extra="forbid"` Pydantic contract (`services/chunker/config.py`),
loaded via `load_config(path, **overrides)`. The shipped production profile
is [`configs/chunker_production.yaml`](../../configs/chunker_production.yaml).
Every effective configuration is hashed (`config_hash()`) and recorded in
`manifest.json`.

Invalid combinations are rejected at load time (a `pydantic.ValidationError`,
never a silent clamp) — see the `@model_validator` in `config.py`.

| Parameter | Unit | Default | Purpose | Safe range | Consequence of raising | Consequence of lowering |
|---|---|---|---|---|---|---|
| `tokenizer.name` | HF model id | `sentence-transformers/all-MiniLM-L6-v2` | Which tokenizer measures every chunk's size — must match the embedding model that will eventually consume `retrieval_text` | Any HF `AutoTokenizer`-compatible model id | A larger/different tokenizer changes what "256 tokens" means; re-chunk after changing it | — |
| `tokenizer.revision` | str\|null | `null` | Pin an exact model revision for full reproducibility | Any valid revision/commit | More reproducible, requires re-pinning on model updates | — |
| `max_tokens` | tokens | 256 | Hard ceiling — an ordinary chunk must never exceed this | 64–512 for small sentence-embedding models; match your embedding model's real trained sequence length, not its raw architectural limit (see rationale in `config.py`'s `TokenizerOptions` docstring) | More context per chunk, coarser retrieval granularity, risk of exceeding the *embedding* model's real limit if raised past its trained `max_seq_length` | More, smaller chunks; more atomic-overflow risk for large tables/equations |
| `target_tokens` | tokens | 180 | Soft target the recursive splitter aims for (must be ≤ `max_tokens`) | 60–90% of `max_tokens` | Chunks closer to `max_tokens`, less headroom for heading-context prefixing | Smaller, more numerous recursively-split chunks |
| `min_chunk_tokens` | tokens | 40 | Below this, a chunk is a *candidate* for safe merging (must be < `max_tokens`) | 10–25% of `max_tokens` | Fewer chunks get merged (more small fragments survive) | More aggressive merging — risk of merging genuinely distinct short chunks that happen to share a heading path |
| `text_overlap_tokens` | tokens | 32 | Overlap between adjacent recursively-split TEXT children only (must be < `target_tokens`) | 10–20% of `target_tokens` | More duplicated content across chunk boundaries, better boundary-fact recall | Less duplication, higher risk a fact split exactly at a boundary loses context |
| `recursive_separators` | ordered list[str] | `["\n\n","\n",". ","! ","? ","; ",", "," ",""]` | Boundary preference, strongest to weakest; **must end with `""`** (hard character fallback) | Add/reorder for other languages/document styles | Coarser splits (fewer, larger separators tried first) | Finer splits |
| `merge_small_chunks` | bool | `true` | Enable safe small-sibling merging (TEXT/LIST only — see `merging.py`) | — | More context per chunk, fewer total chunks | More, smaller chunks; nothing merged |
| `repeat_table_headers` | bool | `true` | Repeat the column-header row in every table row-group fragment | — | Larger table fragments (header repeated each time), each independently interpretable | Fragments after the first lose column-header context |
| `include_heading_context` | bool | `true` | Whether `retrieval_text` is prefixed with heading/caption context (`text` is never affected) | — | Better retrieval context, slightly higher `retrieval_text` token count than `token_count` reports (see `OUTPUT_SCHEMA.md`) | `retrieval_text == text` |
| `allowed_atomic_overflow` | bool | `true` | Permit an unsplittable atomic unit (one equation, one table cell/row, one list item) that alone exceeds `max_tokens` to ship flagged rather than be corrupted | — | Large atomic units survive intact but oversized | Such units instead cause a hard validation failure — use only if your embedding step truncates silently and you would rather fail loudly upstream |
| `output_root` | path | `data/output/chunker` | Base directory for run artifacts | Any writable path | — | — |
| `strict` | bool | `false` | Treat warnings as failures (CI gate), mirrors the parser's `--strict` | — | Any warning fails the run | Warnings never fail the run |
| `log_level` | enum | `INFO` | Console/file log verbosity floor | `DEBUG`\|`INFO`\|`WARNING`\|`ERROR` | Quieter | Noisier (DEBUG shows per-stage detail) |

## Adding a new profile

Copy `configs/chunker_production.yaml`, adjust parameters, and pass it via
`engrag-chunk run --profile <path>`. There is currently one shipped profile
(`production`); the `profile` field is a `Literal["production"]` today and
can be widened to an enum of named profiles the same way the parser's
`Profile` enum works, if/when a second profile is needed.

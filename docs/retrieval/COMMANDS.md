# Retrieval Commands

All commands below were run against this repository's real, already-indexed
`engineering_documents_v1` collection (122 chunks: 113 from the Engineering
PDF, 9 from the OCR PDF) as part of this milestone's acceptance evidence —
see `RETRIEVAL_COMPLETION_REPORT.md`.

## Search

```powershell
.\.venv\Scripts\engrag-retrieve.exe search --query "What is the purpose of front-end engineering design?" --profile configs\retrieval_production.yaml --top-k 5
```

Embeds the query with the required BGE query prefix (applied exactly once),
searches the configured collection, and prints rank, chunk_id, source, pages,
section, a score column (labelled by whichever signal actually produced the
final ranking — cosine / rrf / rerank), and a snippet. `--json` emits the
full `RetrievalResponse` on stdout; `--output <path>` additionally writes it
to a file. `--filter KEY=VALUE` (repeatable) applies scalar metadata filters
— consistently across every mode, including fused/reranked results:

```powershell
.\.venv\Scripts\engrag-retrieve.exe search --query "instrument index" --profile configs\retrieval_production.yaml --filter source_filename=Instrumentation-and-Control-Engineering.pdf
```

### Hybrid retrieval + reranking modes

Four supported modes (see `docs/retrieval/HYBRID_RETRIEVAL_ARCHITECTURE.md`):

```powershell
# Mode A — vector only (default; identical behavior to the vector-only milestone)
.\.venv\Scripts\engrag-retrieve.exe search --query "control valve" --profile configs\retrieval_production.yaml --mode vector

# Mode B — vector + BM25 + RRF fusion (requires a built BM25 index, see below)
.\.venv\Scripts\engrag-retrieve.exe search --query "control valve" --profile configs\retrieval_production.yaml --mode hybrid

# Mode C — hybrid + cross-encoder reranking (downloads BAAI/bge-reranker-base on first use)
.\.venv\Scripts\engrag-retrieve.exe search --query "control valve" --profile configs\retrieval_production.yaml --mode hybrid-rerank

# Mode D — vector + reranking, no BM25
.\.venv\Scripts\engrag-retrieve.exe search --query "control valve" --profile configs\retrieval_production.yaml --mode vector-rerank
```

Explicit override flags (`--bm25`/`--no-bm25`, `--rerank`/`--no-rerank`) take
the highest precedence, above `--mode`, above the YAML profile's own
`retrieval.bm25_enabled` / `reranker.enabled`:

```powershell
# Run hybrid mode's BM25+RRF, but force reranking off even if the profile enables it
.\.venv\Scripts\engrag-retrieve.exe search --query "P&ID" --profile configs\retrieval_production.yaml --mode hybrid-rerank --no-rerank
```

An invalid `--mode` value, or a request for a mode whose BM25 index does not
exist or has drifted from the live Chroma collection, exits non-zero with an
explicit error — never a silent fallback to vector-only.

## Inspect a collection

```powershell
.\.venv\Scripts\engrag-retrieve.exe inspect --profile configs\retrieval_production.yaml
.\.venv\Scripts\engrag-retrieve.exe inspect --profile configs\retrieval_production.yaml --collection engineering_documents_v1 --json
```

Non-mutating: prints the database path, collection name, count, distance
metric, embedding dimension, sample metadata keys, and the source-filename
distribution. Never creates a collection.

## Validate

```powershell
.\.venv\Scripts\engrag-retrieve.exe validate --profile configs\retrieval_production.yaml
```

Runs non-destructive compatibility checks (path exists, collection exists,
not empty, embedding dimension matches the profile, distance metric is
cosine, stored model name matches the profile). Exit code `0` on PASS, `1` on
FAIL. Never embeds a query or writes anything.

## Build the BM25 lexical index

```powershell
.\.venv\Scripts\engrag-retrieve.exe build-bm25 --profile configs\retrieval_production.yaml
```

Deliberate and explicit — no search command ever builds or mutates this
index implicitly. Reads the live Chroma collection **read-only** (the same
`chunk_id`/`retrieval_text`/metadata every vector hit already carries) and
writes a persistent BM25 index atomically at `bm25.index_path`
(`data/output/databases/bm25/<collection_name>/` by default). Idempotent:
rerunning against an unchanged collection is a no-op unless `--force` is
given. Required once before `--mode hybrid`/`hybrid-rerank` will run;
`--json` emits the manifest (corpus count, fingerprint, document/filename
sets, library/tokenizer versions) on stdout.

## Evaluate

```powershell
.\.venv\Scripts\engrag-retrieve.exe evaluate --profile configs\retrieval_production.yaml
```

Runs the ground-truth benchmark (`data/eval/retrieval_ground_truth.jsonl`, 20
cases) at K = 1, 3, 5, 10 and writes a full report under
`data/output/retrieval/<RUN_ID>/`. Accepts the same `--mode` /
`--bm25`/`--no-bm25` / `--rerank`/`--no-rerank` flags as `search`, so the
identical dataset and metrics can be run against every mode for a fair
comparison:

```powershell
.\.venv\Scripts\engrag-retrieve.exe evaluate --profile configs\retrieval_production.yaml --mode vector
.\.venv\Scripts\engrag-retrieve.exe evaluate --profile configs\retrieval_production.yaml --mode hybrid
.\.venv\Scripts\engrag-retrieve.exe evaluate --profile configs\retrieval_production.yaml --mode vector-rerank
.\.venv\Scripts\engrag-retrieve.exe evaluate --profile configs\retrieval_production.yaml --mode hybrid-rerank
```

Each run's `retrieval_evaluation_summary.md` records the effective
`retrieval_mode`/`bm25_enabled`/`reranker_enabled` alongside the metrics
table, so historical runs stay distinguishable. See
`docs/retrieval/EVALUATION.md` for the metrics, dataset methodology, and the
cross-mode comparison table.

## Version / help

```powershell
.\.venv\Scripts\engrag-retrieve.exe --version
.\.venv\Scripts\engrag-retrieve.exe --help
.\.venv\Scripts\engrag-retrieve.exe search --help
```

## Test suites

```powershell
.\.venv\Scripts\python.exe -m pytest -m "not slow"                 # fast suite, fake embedder + fake reranker, no network
.\.venv\Scripts\python.exe -m pytest -m slow -p no:cacheprovider   # includes real BGE model, real collection, real reranker
.\.venv\Scripts\python.exe -m pytest -m "not slow" --cov=engineering_rag --cov-report=term-missing
```

Fast tests never download the real cross-encoder or BM25s from the network —
`tests/support/fake_reranker.py` and a real, ephemeral, `tmp_path`-rooted
`bm25s` index cover every hybrid-mode code path. Real-model hybrid tests live
in `tests/integration/services/retriever/test_hybrid_real_retrieval.py`,
marked `slow`, and self-skip if the local collection or the local BM25 index
is not present.

## Quality gates

```powershell
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe src
.\.venv\Scripts\python.exe -m build --wheel
```

## Prerequisite: an indexed collection

Retrieval never creates a collection. If `engrag-retrieve inspect` reports no
collection, run the indexing milestone's build first (see
`docs/indexing/COMMANDS.md`):

```powershell
.\.venv\Scripts\engrag-index.exe build --input "data\output\chunker\Instrumentation-and-Control-Engineering\<bge-run-id>" --profile configs\indexing_production.yaml
```

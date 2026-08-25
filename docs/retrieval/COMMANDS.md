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
searches the configured collection, and prints rank, chunk_id, similarity,
distance, source, pages, section and a snippet. `--json` emits the full
`RetrievalResponse` on stdout; `--output <path>` additionally writes it to a
file. `--filter KEY=VALUE` (repeatable) applies scalar metadata filters:

```powershell
.\.venv\Scripts\engrag-retrieve.exe search --query "instrument index" --profile configs\retrieval_production.yaml --filter source_filename=Instrumentation-and-Control-Engineering.pdf
```

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

## Evaluate

```powershell
.\.venv\Scripts\engrag-retrieve.exe evaluate --profile configs\retrieval_production.yaml
```

Runs the ground-truth benchmark (`data/eval/retrieval_ground_truth.jsonl`, 20
cases) at K = 1, 3, 5, 10 and writes a full report under
`data/output/retrieval/<RUN_ID>/`. See `docs/retrieval/EVALUATION.md` for the
metrics and dataset methodology.

## Version / help

```powershell
.\.venv\Scripts\engrag-retrieve.exe --version
.\.venv\Scripts\engrag-retrieve.exe --help
.\.venv\Scripts\engrag-retrieve.exe search --help
```

## Test suites

```powershell
.\.venv\Scripts\python.exe -m pytest -m "not slow"                 # fast suite, fake embedder, no network
.\.venv\Scripts\python.exe -m pytest -m slow -p no:cacheprovider   # includes real BGE model + real collection
.\.venv\Scripts\python.exe -m pytest -m "not slow" --cov=engineering_rag --cov-report=term-missing
```

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

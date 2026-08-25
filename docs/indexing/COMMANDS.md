# Indexing Commands

All commands below were run against this repository's real BGE-aligned
chunk runs as part of this milestone's acceptance evidence (see
`INDEXING_COMPLETION_REPORT.md`).

## Build (embed + store)

```powershell
.\.venv\Scripts\engrag-index.exe build --input "data\output\chunker\Instrumentation-and-Control-Engineering\<bge-run-id>" --profile configs\indexing_production.yaml
.\.venv\Scripts\engrag-index.exe build --input "data\output\chunker\scanned_docling_test_image_only\<bge-run-id>" --profile configs\indexing_production.yaml
```

`--input` accepts either a chunker run directory or a direct path to its
`chunks.jsonl`. `--rebuild` destructively replaces the target collection
(requires `chroma.allow_rebuild: true` in the profile). `--json` emits a
machine-readable summary on stdout instead of Rich console output.

## Inspect a collection

```powershell
.\.venv\Scripts\engrag-index.exe inspect --profile configs\indexing_production.yaml
.\.venv\Scripts\engrag-index.exe inspect --profile configs\indexing_production.yaml --collection engineering_documents_v1 --json
```

Prints the collection's count and its full stored identity metadata (model
name, dimension, distance metric, tokenizer, corpus id, schema version).

## Validate a completed run

```powershell
.\.venv\Scripts\engrag-index.exe validate --run "data\output\indexing\engineering_documents_v1\<run-id>"
.\.venv\Scripts\engrag-index.exe validate --run "data\output\indexing\engineering_documents_v1\<run-id>" --strict
```

Re-evaluates the stored `index_validation_report.json`; `--strict` escalates
warnings to failures. Exit code `0` on `PASS`/`PASS_WITH_WARNINGS`,
`1` on `FAIL`.

## List collections

```powershell
.\.venv\Scripts\engrag-index.exe list --profile configs\indexing_production.yaml
```

Lists every collection present at the profile's `chroma.persistence_path`,
with counts.

## Diagnostic smoke query (not the retrieval API)

```powershell
.\.venv\Scripts\engrag-index.exe smoke-query --query "What is a control system?" --profile configs\indexing_production.yaml --collection engineering_documents_v1 --top-k 5
```

Embeds the query with the required BGE query prefix, runs a raw Chroma
similarity search, and prints `chunk_id` / distance / heading / snippet.
Explicitly diagnostic — no reranking, no hybrid search, no filtering.

## Version / help

```powershell
.\.venv\Scripts\engrag-index.exe --version
.\.venv\Scripts\engrag-index.exe --help
.\.venv\Scripts\engrag-index.exe build --help
```

## Chunker: producing a BGE-compatible chunk run

The embedding milestone requires chunk runs whose tokenizer matches the
embedding model exactly (see `VALIDATION.md` gate 3). Use the BGE-aligned
chunker profile, not `chunker_production.yaml`:

```powershell
.\.venv\Scripts\engrag-chunk.exe run --input "data\output\parser\Instrumentation-and-Control-Engineering\20260824T124235Z-01e4d6fa" --profile configs\chunker_bge.yaml
.\.venv\Scripts\engrag-chunk.exe run --input "data\output\parser\scanned_docling_test_image_only\20260824T130311Z-57f84fd5" --profile configs\chunker_bge.yaml
```

## Test suites

```powershell
.\.venv\Scripts\python.exe -m pytest -m "not slow"                 # fast suite, deterministic fake embedder, no network
.\.venv\Scripts\python.exe -m pytest -m slow -p no:cacheprovider   # full suite incl. real BGE model + real Docling
.\.venv\Scripts\python.exe -m pytest -m "not slow" --cov=engineering_rag --cov-report=term-missing
```

## Quality gates

```powershell
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe src
.\.venv\Scripts\python.exe -m build --wheel
```

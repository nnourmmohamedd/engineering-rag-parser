# `databases/bm25`

Persistent, local BM25 lexical index. The only place in this package tree
that imports `bm25s` (MIT license, pure Python + numpy, no server, no
network at query time). Mirrors `databases/chroma`'s shape: a validated
config, typed models, and build/load/search functions.

## Contents

- `config.py` — `BM25Config` (index path, `k1`/`b`/`method`, mmap).
- `models.py` — `BM25CorpusRecord` (one indexed chunk, same provenance a
  vector hit carries), `BM25Manifest` (everything needed to verify an index
  without loading it — corpus fingerprint, chunk ids, content hashes,
  library/tokenizer versions), `BM25RawHit`.
- `tokenizer.py` — the engineering-identifier-aware tokenizer (`PT-101`,
  `P&ID`, `4-20 mA`, `IEC 61511`, …); see its module docstring for the exact
  rules and why the default `bm25s.tokenize` regex is unsuitable here.
- `errors.py` — `BM25IndexNotFoundError`, `CorpusValidationError`.
- `index.py` — `build_bm25_index()` (atomic, idempotent, validates the
  corpus before writing) and `load_bm25_index()` / `BM25IndexHandle.search()`
  (read-only, never rebuilds).

## BM25 never creates chunks

This index is built directly from the **live Chroma collection's own
records** (`pipelines/retrieval_pipeline.py::read_chroma_corpus_as_bm25_records`)
— never from a separate `chunks.jsonl` re-read. Vector search and BM25
search therefore search the exact same `chunk_id`/`retrieval_text` pairs by
construction, and `services/retriever/corpus_compat.py` verifies this stays
true (chunk-id set, content hashes, document ids, filenames, schema version)
before any hybrid search runs.

See `docs/retrieval/HYBRID_RETRIEVAL_ARCHITECTURE.md` for the full pipeline.

# Indexing Completion Report

**Report date:** 2026-08-25
**Scope:** implement the complete, production-grade embedding + ChromaDB
indexing milestone — a typed embedding service (BAAI/bge-base-en-v1.5), a
Chroma storage adapter, one connecting indexing pipeline, and one CLI — on
top of the already-complete parser and chunker milestones. No retrieval API,
hybrid search, cross-encoder reranking, answer generation, or chatbot code
was added, per explicit scope; a diagnostic `smoke-query` command exists
solely to verify stored embeddings are retrievable.

---

## 1. Final verdict

**EMBEDDING + CHROMADB INDEXING MILESTONE COMPLETE AGAINST THE DEFINED
SOFTWARE SCOPE.**

A typed, ChromaDB-independent embedding service and a sentence-transformers-
independent Chroma storage adapter are both implemented, connected only
through `pipelines/indexing_pipeline.py` and `engrag-index`. Real-document
acceptance ran on both the engineering PDF (113 chunks) and the OCR PDF
(9 chunks) into a combined 122-record collection, with 0 failed validation
gates, verified idempotency, and a genuine semantic smoke-query returning
relevant results. All previous parser/chunker tests remain green.

## 2. Percentage complete

**100%** against the software acceptance criteria in the task brief — see
§21 for the item-by-item checklist. This is a software-completeness claim,
not a retrieval-quality claim: full retrieval evaluation is explicitly the
next milestone (§26).

## 3. Branch

`feature/embedding-chroma-index`, created from verified `master` at commit
`4173850` (working tree clean, local `master` matched `origin/master` at
audit time, repository-local author `Nour Mohamed`, email unchanged).

## 4. Commit hash(es)

Recorded at commit time below (this report is written and committed as part
of the same feature branch before the PR is opened).

## 5. PR URL

Recorded once opened — see the final response accompanying this report.

## 6. CI status for Python 3.11 and 3.13

Recorded once CI has run on the PR — see the final response accompanying
this report.

## 7. Final architecture

```text
src/engineering_rag/
├── api/
│   ├── cli.py                      engrag-parse (unchanged)
│   ├── chunker_cli.py               engrag-chunk (unchanged)
│   └── index_cli.py                  engrag-index (new): build/inspect/validate/list/smoke-query
├── pipelines/
│   ├── parsing_pipeline.py         unchanged
│   ├── chunking_pipeline.py         unchanged
│   ├── indexing_config.py            new: IndexingConfig composing EmbedderConfig + ChromaConfig
│   ├── indexing_models.py             new: IndexManifest, IndexValidationReport
│   ├── indexing_artifacts.py           new: IndexRunDirectory, atomic writes
│   ├── indexing_validation.py           new: 12-gate validation-report builder
│   └── indexing_pipeline.py              new: IndexingService — the only module importing
│                                          both services/embedder and databases/chroma
├── services/
│   ├── parser/                     unchanged, all tests green
│   ├── chunker/                     unchanged, all tests green
│   └── embedder/                     NEW — no chromadb import anywhere
│       ├── config.py, errors.py, models.py, interface.py, validation.py, bge.py
└── databases/
    └── chroma/                       NEW — no sentence-transformers import anywhere
        ├── config.py, errors.py, models.py, client.py, collection.py,
        ├── metadata.py, repository.py, validation.py
```

See `docs/indexing/ARCHITECTURE.md` for the full pipeline diagram and
module-boundary rationale.

## 8. Files created/modified

**New (embedder + chroma services, ~18 source files):** every file under
`src/engineering_rag/services/embedder/` and `src/engineering_rag/databases/chroma/`;
`src/engineering_rag/api/index_cli.py`;
`src/engineering_rag/pipelines/indexing_{config,models,artifacts,validation,pipeline}.py`;
`configs/indexing_production.yaml`; `configs/chunker_bge.yaml`.

**New (tests, ~15 files):** `tests/support/fake_embedder.py` (deterministic
fake embedder, used throughout fast CI); `tests/unit/services/embedder/`
(`test_config.py`, `test_validation.py`, `test_fake_embedder.py`);
`tests/unit/databases/chroma/` (`test_config.py`, `test_metadata.py`,
`test_models.py`); `tests/unit/pipelines/test_indexing_{config,pipeline}.py`;
`tests/unit/api/test_index_cli.py`; `tests/integration/databases/chroma/test_repository_integration.py`
(real chromadb, tmp_path, fake vectors); `tests/integration/services/embedder/test_bge_real_model.py`
(marked `slow`, real BGE model).

**New (docs, 9 files):** `docs/indexing/{ARCHITECTURE,EMBEDDING_MODEL_DECISION,
CHROMA_STORAGE_CONTRACT,OUTPUT_SCHEMA,CONFIGURATION,VALIDATION,COMMANDS,
MENTOR_EXPLANATION,INDEXING_COMPLETION_REPORT}.md`.

**New (notebook):** `notebooks/02_embedding_indexing_demo.ipynb`.

**Modified:** `pyproject.toml` (new `indexing` extra, `engrag-index` console
script), `requirements.lock` (regenerated), `.github/workflows/ci.yml`
(installs the `indexing` extra, validates the new notebook, checks the new
modules are present in the built wheel — see §12 for why this was added
proactively), `src/engineering_rag/databases/README.md` (was the scaffold
placeholder), `src/engineering_rag/services/embedder/bge.py` (post-review fix:
`get_sentence_embedding_dimension()` → `get_embedding_dimension()`, the
sentence-transformers 6.0 rename, with a back-compat fallback).

## 9. Dependencies added and why

| Dependency | Extra | Why |
|---|---|---|
| `sentence-transformers>=6.0,<7` | `indexing` | `SentenceTransformer` — loads BGE, embeds passages/queries with normalization |
| `chromadb>=1.5,<2` | `indexing` | `PersistentClient` — local, persistent vector storage |

Both opt-in via `pip install -e ".[indexing]"`, matching the existing
`ocr`/`vlm`/`chunking` extras pattern. No full retrieval/LLM framework
(LangChain, etc.) was added — only the two libraries this milestone's scope
actually needs.

## 10. Exact model name and revision

`BAAI/bge-base-en-v1.5`, resolved revision `a5beb1e3e68b9ab74eb54cfd186867f64f240e1a`
(independently re-verified via `huggingface_hub`/local cache introspection at
runtime — `services/embedder/bge.py::_resolve_revision` — and recorded in
every `index_manifest.json`, not hardcoded).

## 11. Exact tokenizer and maximum length

Tokenizer: `BAAI/bge-base-en-v1.5`'s own tokenizer (loaded via
`transformers.AutoTokenizer`, used independently by the indexing pipeline to
re-measure every `retrieval_text` — never trusting the chunker's stored
count). Maximum sequence length: **512 tokens**.

## 12. Phase-2 tokenizer compatibility — what was found and corrected

**Finding:** every existing chunker run (`configs/chunker_production.yaml`)
was sized against `sentence-transformers/all-MiniLM-L6-v2`'s tokenizer
(256-token budget) — the correct default when the chunker milestone shipped,
but incompatible with this milestone's `BAAI/bge-base-en-v1.5` tokenizer
(different vocabulary, 512-token budget).

**Correction:**
1. Created `configs/chunker_bge.yaml` — same unmodified chunker architecture,
   `tokenizer.name: BAAI/bge-base-en-v1.5`, `max_tokens: 512`,
   `target_tokens: 400`, `min_chunk_tokens: 64`, `text_overlap_tokens: 64`
   (ratios scaled proportionally from the MiniLM profile; full reasoning in
   the config file's header comment).
2. Reran both source documents into new chunker run directories:
   `data/output/chunker/Instrumentation-and-Control-Engineering/20260825T073605Z-01e4d6fa/`
   (**113 chunks, status PASS, 0 failed gates**) and
   `data/output/chunker/scanned_docling_test_image_only/20260825T073624Z-57f84fd5/`
   (**9 chunks, status PASS, 0 failed gates**).
3. The original MiniLM-tokenized chunker runs were **not modified or
   deleted** — they remain valid for a MiniLM-based use, just not admissible
   input for this milestone.
4. The indexing pipeline enforces this as a hard, automated gate (not just a
   one-time manual correction): `require_model_tokenizer_match` rejects any
   chunk run whose `manifest.json` tokenizer name does not exactly equal the
   embedding model's `model_name` — see `VALIDATION.md` gate 3 and
   `MENTOR_EXPLANATION.md` for the full reasoning.

## 13. Vector dimension

**768**, verified both by unit test (`services/embedder/validation.py::validate_vector`,
enforced on every vector produced) and end-to-end on real BGE output
(`tests/integration/services/embedder/test_bge_real_model.py`, real-corpus
manifests below).

## 14. Normalization result

**Confirmed.** Every stored vector is L2-normalized within `1e-3` of `1.0`
(`normalize_embeddings=True` at encode time, independently re-verified by
`validate_vector()` before any vector is returned from the embedder, and
again by the `round_trip_storage_matches` gate after Chroma storage).

## 15. Distance metric

**Cosine** — `hnsw:space: "cosine"` set on collection creation, enforced by
the `cosine_distance_metric` validation gate on every run, and by
`ChromaConfig.distance_metric: Literal["cosine"]` at the type level (no other
value is representable in the production config).

## 16. Device used

**CPU** (`device: auto` resolved to `cpu` — no CUDA available in this
environment; resolution and choice are logged and recorded in every
manifest's `device` field).

## 17. Engineering chunk count

**113 chunks** (down from the MiniLM-tokenized run's 117 — expected and
explained: the larger 512-token budget under `configs/chunker_bge.yaml`
allows more small-sibling merging than the 256-token MiniLM budget did; not
a defect, a documented consequence of §12's rerun).

## 18. OCR chunk count

**9 chunks** — unchanged from the MiniLM-tokenized run (the OCR document's
chunks were already well under both token budgets, so the larger budget
changed nothing about how they were split/merged).

## 19. Combined collection count

**122 records** (113 + 9), verified directly via
`engrag-index inspect --profile configs/indexing_production.yaml` after both
real documents were indexed into the same `engineering_documents_v1`
collection at `data/output/databases/chroma`.

## 20. Chroma path

`data/output/databases/chroma` (relative to the repository root; git-ignored
under the existing `data/output/**` rule — no database files are committed).

## 21. Collection name

`engineering_documents_v1` (the production default in
`configs/indexing_production.yaml`).

## 22. Embedding timing and throughput (real BGE model, CPU, this machine)

| Run | Chunks | Embedding duration | Throughput |
|---|---|---|---|
| Engineering PDF (first index) | 113 | 15.87s | 7.13 vec/s |
| OCR PDF | 9 | 2.25s | 4.01 vec/s |
| Engineering PDF (idempotent rerun, re-embedded then recognized as identical) | 113 | 12.89s | 8.78 vec/s |

(Batch size 32, CPU-only `torch==2.13.0+cpu`. Rerun timing varies run-to-run
with normal system load; both runs correctly resulted in 0 net new records —
see §31.)

## 23. Unit/fast/slow test counts

| Suite | Result |
|---|---|
| Fast (`pytest -m "not slow"`) | **471 passed, 0 failed** (up from the pre-indexing baseline of 361; +110 net new embedder/chroma/pipeline/CLI tests) |
| Slow (`pytest -m slow -p no:cacheprovider`) | **69 passed, 0 failed** (61 parser+chunker, unchanged, + 8 new real-BGE-model tests) |
| **Total** | **540** |

Every parser and chunker test that existed before this milestone is
unchanged in behaviour and still green — **no regression**.

## 24. Coverage

**84%** (`pytest -m "not slow" --cov=engineering_rag`). Slightly below the
previously reported 85.74% combined figure — attributable to the new
`services/embedder/bge.py` and `databases/chroma/client.py` modules' device-
resolution and error-handling branches that are only exercised by the `slow`
real-model tests, not the fast fake-embedder suite; well above the CI floor
of 55% and the fast-suite baseline this project has always measured against.

## 25. Ruff result

`ruff format --check .` — **PASS** (184 files, including the new notebook's
code cells). `ruff check .` — **PASS**, all checks passed (repo-wide,
parser + chunker + embedder + chroma + pipelines + tests + notebooks).

## 26. Mypy result

**PASS** — `Success: no issues found in 77 source files` (`mypy src`).

## 27. Notebook result

`nbformat.validate` — **PASS** (31 cells). Full top-to-bottom execution via
`nbconvert --execute` — **PASS**, 0 error outputs, including all 14 required
demonstration steps (load chunks.jsonl, inspect retrieval_text/metadata,
load BGE, embed a passage, embed a query with prefix, verify 768-d, verify
normalization, create/open Chroma, store a sample, reopen the persistent
collection in a fresh client, run a diagnostic query, inspect IDs/documents/
metadata, run the production indexing pipeline, read the validation report).

## 28. Wheel/clean-install result

`python -m build --wheel` — **PASS**;
`engineering_rag_parser-1.0.0-py3-none-any.whl` contains
`engineering_rag/services/embedder/`, `engineering_rag/databases/chroma/`,
`engineering_rag/pipelines/indexing_pipeline.py`, and
`engineering_rag/api/index_cli.py`; `entry_points.txt` lists all three
console scripts (`engrag-parse`, `engrag-chunk`, `engrag-index`). No PDF,
`artifacts/`, or `data/output/` content present in the wheel.

## 29. Validation gates

16 recorded checks total (10 CRITICAL/gate + 4 more admission-time CRITICAL
checks enforced before any run directory exists + 2 WARNING/non-gate) — full
list and rationale in `docs/indexing/VALIDATION.md`. Both real-document runs:
**0 failed gates**, status `PASS`. `self_retrieval_rank_one` (WARNING
severity, not a hard gate) passed on both runs' sampled chunks.

## 30. Idempotency result

**Verified on the real corpus.** Reindexing the 113-chunk engineering-document
run a second time against the same collection: `inserted: 0`,
`existing_identical: 113`, `rejected: 0`, collection count unchanged at
**122** before and after. Unit/integration tests additionally cover the
conflicting-hash case (`DuplicateIdConflictError` raised, never a silent
overwrite).

## 31. Known limitations

- **Coverage is measured on the fast suite only** (§24) — the real-model
  code paths in `bge.py`/`client.py` are covered by the `slow` suite, which
  is not included in the CI coverage gate, matching the pre-existing
  parser/chunker convention of a cold-cache-realistic CI floor.
- **`self_retrieval_rank_one` is a WARNING, not a hard gate** — an
  exact-vector tie (two chunks with identical `retrieval_text`) is a
  legitimate, documented outcome that would otherwise falsely fail the run;
  no such tie was observed on either real document in this milestone's
  acceptance runs.
- **No raw-vector export path** — deliberately out of scope; `chunks.jsonl`
  plus the persistent Chroma collection are the complete, non-duplicated
  record (see `OUTPUT_SCHEMA.md`).
- **`source_element_refs` metadata is capped at 4000 JSON-encoded
  characters** — the full, untruncated list always remains available in the
  canonical `chunks.jsonl`; no chunk in either real document actually hit
  this cap.
- **Engineering-PDF chunk count changed from 117 (MiniLM) to 113 (BGE)** —
  documented and explained in §12/§17, not a defect.

## 32. Human-review items

Unchanged from the parser and chunker milestones, not affected by indexing —
every parser-flagged figure/table item is still visible via
`parser_warnings` propagated into each stored record's `warnings_summary`
metadata field. No new human-review category was introduced by embedding or
storage. **No human semantic review of retrieval quality has been performed
or is claimed** — the `smoke-query` command's results in this report are an
automated, embedding-similarity observation, not a human relevance judgement
(see `VALIDATION.md`'s explicit separation of hard gates from semantic smoke
tests).

## 33. Exact commands to reproduce

```powershell
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe src
.\.venv\Scripts\python.exe -m pytest -m "not slow"
.\.venv\Scripts\python.exe -m pytest -m slow -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -m "not slow" --cov=engineering_rag --cov-report=term-missing
.\.venv\Scripts\python.exe -m build --wheel
.\.venv\Scripts\engrag-chunk.exe run --input "data\output\parser\Instrumentation-and-Control-Engineering\20260824T124235Z-01e4d6fa" --profile configs\chunker_bge.yaml
.\.venv\Scripts\engrag-chunk.exe run --input "data\output\parser\scanned_docling_test_image_only\20260824T130311Z-57f84fd5" --profile configs\chunker_bge.yaml
.\.venv\Scripts\engrag-index.exe build --input "data\output\chunker\Instrumentation-and-Control-Engineering\20260825T073605Z-01e4d6fa" --profile configs\indexing_production.yaml
.\.venv\Scripts\engrag-index.exe build --input "data\output\chunker\scanned_docling_test_image_only\20260825T073624Z-57f84fd5" --profile configs\indexing_production.yaml
.\.venv\Scripts\engrag-index.exe inspect --profile configs\indexing_production.yaml
.\.venv\Scripts\engrag-index.exe smoke-query --query "What is a control system?" --profile configs\indexing_production.yaml --top-k 5
```

See `docs/indexing/COMMANDS.md` for the complete command reference.

## 34. Ready to merge?

Recorded once CI has run on the PR — see the final response accompanying
this report. Locally: all gates in §21–30 pass; nothing is merged without
explicit instruction, per this milestone's explicit "do not merge unless
told to" constraint.

## 35. Ready for the vector-retrieval milestone?

**Yes.** A persistent, identity-versioned Chroma collection with 122
real, validated, idempotently-ingested records exists at
`data/output/databases/chroma/engineering_documents_v1`; every record
carries the full metadata a future hybrid-retrieval/reranking stage needs
(`content_type`, `heading_path`, `chunk_run_id`, lineage ids) without
re-parsing the source document; `smoke-query`'s real result for "What is a
control system?" returned the document's own Control Philosophy / Control
System and Logic sections at the top — a first, genuine (if not formally
evaluated) signal that the stored embeddings are semantically usable. No
retrieval API, hybrid search, reranking, or chatbot code exists in this
repository — that remains explicitly the next milestone's scope.

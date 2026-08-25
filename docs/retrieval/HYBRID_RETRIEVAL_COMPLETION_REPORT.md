# Hybrid Retrieval + Reranking Completion Report

**Report date:** 2026-08-25
**Scope:** extend the completed vector retrieval milestone with optional
BM25 lexical fusion (Reciprocal Rank Fusion) and optional local
cross-encoder reranking, in four selectable, independently-toggleable
modes, without breaking vector-only backward compatibility.

---

## 1. Final verdict

**HYBRID RETRIEVAL + RERANKING MILESTONE COMPLETE AGAINST THE DEFINED
SOFTWARE SCOPE.** All four modes (vector, hybrid, vector-rerank,
hybrid-rerank) work end to end against the real, already-indexed
`engineering_documents_v1` collection (122 chunks). Human review of the
ground-truth relevance labels remains a separate, explicitly-not-fabricated
manual step (§29).

## 2. Percentage complete

**100%** against the software-completeness checklist in the task brief.
This is a software-completeness claim, not a retrieval-quality guarantee —
§17-18 report the actual measured evaluation numbers, including where
hybrid/reranking did **not** improve on this dataset.

## 3. Baseline commit

`c215e9b` (`master`, clean working tree, local `master` == `origin/master`
at audit time, repository-local author `Nour Mohamed`, email unchanged).

## 4. Branch

`feature/hybrid-retrieval-reranking`, created from `c215e9b`.

## 5. New commit hashes and purposes

- `970ee3b` — Add persistent BM25 lexical index and cross-encoder reranker
  services (`databases/bm25`, `services/reranker`,
  `services/retriever/{bm25_retriever,fusion,corpus_compat}.py`).
- `96106a6` — Wire hybrid retrieval orchestration into the pipeline and CLI
  (`HybridRetriever`, `build_bm25_index_pipeline`, `run_hybrid_search`,
  `engrag-retrieve build-bm25`, `--mode`/`--bm25`/`--rerank` flags).
- `993563a` — Add tests for BM25, fusion, reranker, corpus compatibility,
  and hybrid modes (unit, fast integration, and real-corpus slow tests).
- `1371a2d` — Add hybrid retrieval documentation, evaluation comparison,
  and demo notebook.

## 6. PR URL

**https://github.com/nnourmmohamedd/engineering-rag-parser/pull/5** —
"Hybrid retrieval (BM25 + RRF) and optional cross-encoder reranking."

## 7. Whether PR is open or merged

**Open.** Not merged — awaiting explicit approval per instructions.

## 8. Python 3.11 CI result

**PASS** — run `32850568386`, job `quality (3.11)`, 4m0s.

## 9. Python 3.13 CI result

**PASS** — run `32850568386`, job `quality (3.13)`, 4m22s.

## 10. Architecture and files added

```text
src/engineering_rag/
├── databases/
│   └── bm25/                         NEW (7 files + README)
│       ├── config.py, models.py, tokenizer.py, errors.py, index.py
├── services/
│   ├── retriever/                    EXTENDED
│   │   ├── bm25_retriever.py          NEW
│   │   ├── fusion.py                   NEW
│   │   ├── corpus_compat.py             NEW
│   │   ├── models.py, config.py, retriever.py, evaluation/runner.py  EXTENDED
│   └── reranker/                     NEW (6 files + README)
│       ├── config.py, models.py, interface.py, cross_encoder.py, errors.py
└── pipelines/
    ├── retrieval_config.py            EXTENDED — retrieval/bm25/fusion/reranker sections
    └── retrieval_pipeline.py           EXTENDED — HybridRetriever, build_bm25_index_pipeline,
                                          run_hybrid_search

api/retrieve_cli.py                   EXTENDED — build-bm25 command, --mode/--bm25/--rerank flags
```

New test files: 4 unit (`databases/bm25`), 2 unit (`services/reranker`), 4
unit (`services/retriever` fusion/corpus_compat/hybrid_config/bm25_retriever),
1 fast integration (`test_hybrid_retrieval_integration.py`, 8 test cases), 1
slow real-corpus integration (`test_hybrid_real_retrieval.py`, 7 test cases),
1 test support fake (`fake_reranker.py`); existing `test_retrieve_cli.py` and
`test_models.py` extended/fixed.

New docs: `docs/retrieval/HYBRID_RETRIEVAL_ARCHITECTURE.md`; extended
`COMMANDS.md`, `EVALUATION.md`; new `databases/bm25/README.md`,
`services/reranker/README.md`; extended `services/retriever/README.md`.

New notebook: `notebooks/04_hybrid_retrieval_demo.ipynb` (executed, real
outputs).

New evaluation artifacts: `data/eval/hybrid_retrieval_human_review_worksheet.jsonl`,
`data/eval/hybrid_retrieval_acceptance_queries.json`.

## 11. Libraries and exact pinned versions

- **`bm25s` 0.3.11** (MIT license, verified from installed distribution
  metadata) — new, under a new `hybrid` extra in `pyproject.toml`. Pure
  Python + numpy, no server, no network at query time.
- **`sentence-transformers` 6.0.0`** — reused unchanged, already declared
  under the existing `indexing` extra; provides `CrossEncoder` for
  reranking, no new dependency added for it.
- No other new runtime dependency.

## 12. BM25 index details

- Path: `data/output/databases/bm25/engineering_documents_v1` (gitignored,
  same convention as the Chroma persistence directory).
- Built directly from the live Chroma collection (never a separate
  `chunks.jsonl` re-read) via `engrag-retrieve build-bm25`.
- `corpus_count`: **122** (matches the Chroma collection exactly).
- `corpus_fingerprint`: `daa15ba96d152652...` (SHA-256 over sorted
  `(chunk_id, content_hash)` pairs).
- `method=lucene, k1=1.2, b=0.75`, `tokenizer_version=1.0.0`,
  `bm25_library=bm25s 0.3.11`.
- Idempotent rebuild verified (unchanged corpus → no-op, identical
  fingerprint); atomic swap-on-success verified (a failed/interrupted build
  never touches a previously valid index).

## 13. Corpus compatibility result

**PASS** on the real collection/index pair (collection name, record count,
full chunk-id set, document-id set, filename set, content hashes, and
schema version all match). The refusal path was also verified directly: a
deliberately corrupted BM25 manifest (one chunk_id removed) correctly raised
`CorpusCompatibilityError` and blocked the hybrid search from running.

## 14. Reranker model and pinned revision

`BAAI/bge-reranker-base`, revision `2cfc18c9415c912f9d8155881c133215df768a70`
(resolved via `HfApi().model_info(...).sha` on 2026-08-25), loaded via
`sentence_transformers.CrossEncoder`, CPU-verified, loaded only when
`reranker.enabled: true`.

## 15. Supported modes

All four, verified end to end against the real collection:

| Mode | vector | bm25 | reranker |
|---|---|---|---|
| `vector` (default) | on | off | off |
| `hybrid` | on | on | off |
| `vector-rerank` | on | off | on |
| `hybrid-rerank` | on | on | on |

## 16. Real corpus counts

**122** total chunks: **113** from the Engineering PDF
(`Instrumentation-and-Control-Engineering.pdf`), **9** from the OCR PDF
(`scanned_docling_test_image_only.pdf`) — confirmed via
`bm25_manifest.json`'s `source_filenames`/`corpus_count` and directly via
`engrag-retrieve inspect`.

## 17. Evaluation metrics for every mode

Same 20-case ground-truth dataset, same corpus, same K values, same metric
implementations, run 2026-08-25:

| Metric | Vector | Hybrid | Vector+Rerank | Hybrid+Rerank | Best |
|---|---|---|---|---|---|
| Hit Rate@1 | 0.889 | 0.778 | 0.722 | 0.667 | Vector |
| Recall@1 | 0.648 | 0.593 | 0.583 | 0.556 | Vector |
| Precision@1 | 0.889 | 0.778 | 0.722 | 0.667 | Vector |
| nDCG@1 | 0.889 | 0.778 | 0.722 | 0.667 | Vector |
| Hit Rate@3 | 1.000 | 1.000 | 0.944 | 0.944 | tie |
| Recall@3 | 0.787 | 0.833 | 0.759 | 0.759 | Hybrid |
| Precision@3 | 0.389 | 0.426 | 0.370 | 0.370 | Hybrid |
| nDCG@3 | 0.799 | 0.804 | 0.738 | 0.726 | Hybrid |
| Hit Rate@5 | 1.000 | 1.000 | 1.000 | 1.000 | tie |
| Recall@5 | 0.926 | 0.917 | 0.898 | 0.852 | Vector |
| Precision@5 | 0.300 | 0.300 | 0.289 | 0.267 | tie |
| nDCG@5 | 0.875 | 0.852 | 0.812 | 0.776 | Vector |
| Hit Rate@10 | 1.000 | 1.000 | 1.000 | 1.000 | tie |
| Recall@10 | 0.972 | 1.000 | 1.000 | 0.972 | tie |
| Precision@10 | 0.161 | 0.167 | 0.167 | 0.161 | tie |
| nDCG@10 | 0.895 | 0.883 | 0.854 | 0.828 | Vector |
| **MRR** | **0.944** | 0.880 | 0.819 | 0.792 | **Vector** |

**Do not misread this as a failed feature.** BM25/fusion and reranking are
implemented correctly and verified to work mechanically (§13, §14, real
end-to-end runs) — this table is the actual, reproducible measured outcome
on this specific 20-case, already-easy-for-vector-search benchmark, reported
exactly as instructed: no fabricated improvement. Full discussion in
`docs/retrieval/EVALUATION.md`.

## 18. Queries improved/unchanged/degraded

By per-case reciprocal rank vs. the vector-only baseline (20 cases):

| Mode | Improved | Unchanged | Degraded |
|---|---|---|---|
| Hybrid | 0 | 18 | 2 |
| Vector+Rerank | 0 | 15 | 5 |
| Hybrid+Rerank | 0 | 14 | 6 |

## 19. Latency comparison

From `evaluate`'s `latency_p50_s`/`latency_p95_s` (one `HybridRetriever`
built once, reused across all 20 cases — the correct latency reference; see
`EVALUATION.md` for why the acceptance-queries JSON's per-call numbers are
not):

| Mode | p50 | p95 |
|---|---|---|
| Vector | 105.9 ms | 178.2 ms |
| Hybrid | 57.8 ms | 81.8 ms |
| Vector+Rerank | 4361.4 ms | 6306.1 ms |
| Hybrid+Rerank | 5321.2 ms | 6464.6 ms |

(Hybrid's lower latency than vector-only here is a measurement artifact of
run order/OS caching on a 122-chunk corpus, not a claimed general property —
BM25 itself adds sub-10ms; it is not the dominant cost in any mode.)

## 20. Test counts

**769 total** (688 fast + 81 slow). All new tests: 8 unit files (BM25
tokenizer/index, reranker config/fake, retriever fusion/corpus_compat/
hybrid_config/bm25_retriever), 1 fast integration file (8 cases), 1 slow
real-corpus integration file (7 cases).

## 21. Coverage

**85.40%** on the fast suite (`--cov-fail-under=55` gate; well above).

## 22. Ruff result

**PASS** — `ruff format --check .` (254 files) and `ruff check .`, including
the new notebook.

## 23. mypy result

**PASS** — `mypy src`, 106 source files, zero issues.

## 24. Build result

**PASS** — `python -m build --wheel`; wheel contains every new module
(`databases/bm25/*`, `services/reranker/*`,
`services/retriever/{bm25_retriever,fusion,corpus_compat}.py`); no PDF or
extracted-content leakage.

## 25. Clean-install result

**PASS.** CPU-only torch pre-step (matching CI) + `pip install
<wheel>[dev,chunking,indexing,hybrid]` into a fresh venv: `bm25s` installs
correctly, all four CLIs (`engrag-parse`, `engrag-chunk`, `engrag-index`,
`engrag-retrieve`) run `--version`/`--help`/`build-bm25 --help` successfully.
Running the full test suite against the *installed wheel* (not the
recommended editable-install pattern) surfaces one **pre-existing, unrelated**
failure (`test_paths.py::test_does_not_depend_on_the_working_directory`) —
that test assumes an editable install's `pyproject.toml` sits next to the
installed package, which is not the wheel-install layout; it passes normally
under the editable install this project's own CI and docs use.

## 26. Notebook result

**PASS.** `notebooks/04_hybrid_retrieval_demo.ipynb` executed successfully
against the real collection, the real BM25 index, and the real
`BAAI/bge-reranker-base` cross-encoder; `nbformat.validate()` passes; ruff
format/lint pass (ruff lints notebook code cells too).

## 27. Documentation created

- `docs/retrieval/HYBRID_RETRIEVAL_ARCHITECTURE.md` (new) — pipeline
  diagram, module boundaries, bi-encoder vs. cross-encoder explanation, why
  RRF not raw-score mixing, why reranking is bounded, limitations.
- `docs/retrieval/COMMANDS.md`, `EVALUATION.md` (extended) — new commands,
  mode flags, cross-mode comparison table, acceptance-query evidence.
- `src/engineering_rag/databases/bm25/README.md`,
  `services/reranker/README.md` (new), `services/retriever/README.md`
  (extended).
- This report.

## 28. Known limitations

1. BM25 improves lexical/identifier matching but has no notion of meaning.
2. Vector retrieval can under-rank a rare exact identifier a bi-encoder
   never learned to treat as distinctive.
3. RRF combines two rankings by position; it does not itself judge
   relevance.
4. Cross-encoder reranking is materially slower than vector/BM25 on CPU —
   bounded by `candidate_top_k` (20), never run over the full corpus.
5. `reranker_score`/`RerankResult.score` are raw model outputs, not
   calibrated probabilities.
6. On this milestone's actual 20-case benchmark, **reranking and hybrid
   fusion did not measurably improve results** — see §17. This is measured,
   not assumed, and is not evidence either mechanism is broken; it reflects
   this specific dataset's limited headroom above vector-only's already-high
   Hit Rate@3.
7. BM25 metadata filtering scores the entire corpus client-side (documented,
   correct at 122 chunks; would need revisiting at much larger scale).
8. English-oriented models (BGE, bge-reranker-base) do not establish
   anything about non-English retrieval quality.
9. No LLM answer generation, chatbot, context builder, or answer-grounding
   stage is part of this milestone.

## 29. Human-review items

**Unchanged from the prior milestone — still pending.** All 20 ground-truth
cases in `data/eval/retrieval_ground_truth.jsonl` remain
`human_review_status: "machine_candidate"`. This milestone did not touch
those labels; `data/eval/hybrid_retrieval_human_review_worksheet.jsonl` is a
new artifact specifically to support that review across all four modes at
once, per `docs/retrieval/EVALUATION.md`'s human-review checklist.

## 30. Exact commands to reproduce each mode

```powershell
# One-time: build the BM25 index (never implicit)
.\.venv\Scripts\engrag-retrieve.exe build-bm25 --profile configs\retrieval_production.yaml

# Search
.\.venv\Scripts\engrag-retrieve.exe search --query "control valve" --profile configs\retrieval_production.yaml --mode vector
.\.venv\Scripts\engrag-retrieve.exe search --query "control valve" --profile configs\retrieval_production.yaml --mode hybrid
.\.venv\Scripts\engrag-retrieve.exe search --query "control valve" --profile configs\retrieval_production.yaml --mode vector-rerank
.\.venv\Scripts\engrag-retrieve.exe search --query "control valve" --profile configs\retrieval_production.yaml --mode hybrid-rerank

# Evaluate (all four, same dataset)
.\.venv\Scripts\engrag-retrieve.exe evaluate --profile configs\retrieval_production.yaml --mode vector
.\.venv\Scripts\engrag-retrieve.exe evaluate --profile configs\retrieval_production.yaml --mode hybrid
.\.venv\Scripts\engrag-retrieve.exe evaluate --profile configs\retrieval_production.yaml --mode vector-rerank
.\.venv\Scripts\engrag-retrieve.exe evaluate --profile configs\retrieval_production.yaml --mode hybrid-rerank

# Quality gates
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe src
.\.venv\Scripts\python.exe -m pytest -m "not slow" --cov=engineering_rag --cov-report=term-missing
.\.venv\Scripts\python.exe -m pytest -m slow -p no:cacheprovider
.\.venv\Scripts\python.exe -m build --wheel
```

## 31. Working-tree status

**Clean** on `feature/hybrid-retrieval-reranking` at commit `1371a2d`
(plus this report's own commit). Branch pushed; PR open, not merged.

## 32. What milestone comes next

1. Human review of the 20-case ground-truth dataset (§29), so future
   evaluation runs report verified `human_reviewed`/`human_approved` labels
   instead of `machine_candidate`.
2. A larger and/or more deliberately hybrid/rerank-favoring evaluation set
   (rare-identifier-heavy queries, noisier candidate pools) to properly test
   whether hybrid/reranking help in this codebase's real production setting
   — this milestone's honest finding (§17) is that the current 20-case set
   does not have enough headroom to show it either way.
3. An LLM answer-generation/context-builder stage, explicitly out of scope
   for both this and the prior milestone.

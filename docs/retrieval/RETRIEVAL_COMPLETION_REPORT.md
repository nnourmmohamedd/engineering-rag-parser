# Retrieval Completion Report

**Report date:** 2026-08-25
**Scope:** implement vector retrieval + evidence-based retrieval evaluation
on top of the already-complete parser, chunker, and embedding/indexing
milestones — a typed retrieval service (`services/retriever`), one
connecting pipeline, one CLI (`engrag-retrieve`), and a closed-form
evaluation framework against a real, versioned ground-truth dataset. No
BM25, hybrid search, reranking, LLM generation, chatbot API, or UI was
added, per explicit scope.

---

## 1. Final verdict

**VECTOR RETRIEVAL + EVALUATION MILESTONE COMPLETE AGAINST THE DEFINED
SOFTWARE SCOPE.**

A typed, ChromaDB-independent retrieval service reuses the existing BGE
query-embedding support and Chroma adapter unchanged, connected only through
`pipelines/retrieval_pipeline.py` and `engrag-retrieve`. Real queries were
run against the real, already-indexed `engineering_documents_v1` collection
(122 chunks: 113 Engineering PDF, 9 OCR PDF), and a 20-case, hand-built
ground-truth benchmark (evidence pulled directly from the real collection)
was evaluated end to end at K = 1, 3, 5, 10.

## 2. Percentage complete

**100%** against the software acceptance criteria in the task brief (§15) —
see §24 for the item-by-item checklist. This is a software-completeness
claim, not a retrieval-quality guarantee: every evaluation label ships as
`human_review_status: "machine_candidate"` (§24 human-review status), and
`docs/retrieval/EVALUATION.md` documents this honestly.

## 3. Branch

`feature/vector-retrieval-evaluation`, created from verified `master` at
commit `c8b8ef712cf8b75b5abad2fe4f27a191fc0a16f6` (working tree clean, local
`master` matched `origin/master` at audit time, repository-local author
`Nour Mohamed`, email unchanged).

## 4. Commits

`873e687` — "Implement vector retrieval service, pipeline, and CLI
(BAAI/bge-base-en-v1.5)", `248d411` — "Add tests and a real evidence-based
ground-truth dataset for retrieval", `9df045a` — "Wire CI for
engrag-retrieve and add retrieval milestone documentation", `46ca520` —
"Fix: apply ruff format to the retrieval demo notebook", `a3dc486` — "Fix:
remove terminal-width-dependent assertion in CLI help test", all on
`feature/vector-retrieval-evaluation`, branched from verified `master` at
`c8b8ef712cf8b75b5abad2fe4f27a191fc0a16f6`.

## 5. PR link

**Merged.** https://github.com/nnourmmohamedd/engineering-rag-parser/pull/4
— PR #4, "Vector retrieval + evidence-based retrieval evaluation
(BAAI/bge-base-en-v1.5)", merged into `master` as fast-forward merge commit
`0b7f6600a1781cf3f79d62cb276abe23b7fe0c67` on 2026-08-25T10:45:36Z.

## 6. CI status for Python 3.11 and 3.13

**Both PASS**, on every relevant run:
- PR run `32837562046` (commit `a3dc486`): `quality (3.11)` 3m40s,
  `quality (3.13)` 4m6s.
- PR run `32837995427` (after the completion-report update commit
  `b06d833`): both green again.
- **Post-merge run on `master` itself** (`32838826020`, merge commit
  `0b7f660`): `quality (3.11)` **3m46s**, `quality (3.13)` **3m53s**, both
  green.

Two earlier runs on this branch failed and were fixed in follow-up commits,
both caught by CI exactly as intended (root causes below, no gate was
weakened to get around either):

- Run `32836664910` (commit `9df045a`): `ruff format --check` failed — the
  demo notebook was built directly with `nbformat`/executed with `nbclient`
  and never run through `ruff format` locally. Fixed in `46ca520`
  (formatting only, no content/output change).
- Run `32836961135` (commit `46ca520`): `TestVersionAndHelp::test_search_help`
  failed — asserted the literal substring `"--top-k"` in `--help` output,
  which CI's headless 80-column terminal wraps differently than a wide local
  terminal. The existing CLI suites (`test_cli.py`, `test_index_cli.py`,
  `test_chunker_cli.py`) deliberately only assert `exit_code == 0` for
  subcommand `--help` for exactly this reason; fixed in `a3dc486` by
  matching that established convention.

No CI fix was needed at any point after `a3dc486` — the merge itself
(fast-forward, no merge commit content changes) required no additional work.

## 7. Architecture created

```text
src/engineering_rag/
├── api/
│   └── retrieve_cli.py                new: engrag-retrieve — search/inspect/validate/evaluate
├── pipelines/
│   ├── retrieval_config.py             new: RetrievalConfig — composes EmbedderConfig +
│   │                                    ChromaConfig + RetrievalSearchConfig + RetrievalEvaluationConfig
│   ├── retrieval_artifacts.py           new: RetrievalRunDirectory — atomic per-run writes
│   └── retrieval_pipeline.py             new: the ONLY module importing both
│                                          services/retriever AND databases/chroma
└── services/
    └── retriever/                       NEW — no chromadb import anywhere
        ├── config.py, errors.py, models.py, filters.py, retriever.py
        └── evaluation/
            ├── dataset.py, metrics.py, runner.py
```

`services/embedder` and `databases/chroma` are reused **unchanged** — no
existing file in either package was modified by this milestone.

## 8. Files added/changed

**New (retriever service + evaluation, 10 source files):** every file under
`src/engineering_rag/services/retriever/`.

**New (pipeline + CLI, 3 files):** `pipelines/retrieval_{config,artifacts,pipeline}.py`,
`api/retrieve_cli.py`.

**New (config + dataset):** `configs/retrieval_production.yaml`,
`data/eval/retrieval_ground_truth.jsonl` (20 cases).

**New (tests, ~14 files):** `tests/unit/services/retriever/` (models, config,
filters, retriever, evaluation/{metrics,dataset,runner}), `tests/unit/pipelines/
test_retrieval_{config,pipeline}.py`, `tests/unit/api/test_retrieve_cli.py`,
`tests/integration/pipelines/test_retrieval_integration.py`,
`tests/integration/services/retriever/test_bge_real_retrieval.py` (marked
`slow`, real BGE model + real collection).

**New (docs, 5 files):** `services/retriever/README.md`,
`docs/retrieval/{ARCHITECTURE,COMMANDS,EVALUATION,RETRIEVAL_COMPLETION_REPORT}.md`.

**New (notebook):** `notebooks/03_retrieval_evaluation_demo.ipynb`.

**Modified:** `pyproject.toml` (new `engrag-retrieve` console script — no new
dependency; retrieval reuses the existing `indexing` extra's
`sentence-transformers`/`chromadb`), `.github/workflows/ci.yml` (validates
the new notebook, checks the new modules are present in the built wheel),
`.gitignore` (added `!data/eval/*.jsonl` so the versioned ground-truth
dataset is tracked despite the blanket `*.jsonl` rule for generated
artifacts).

## 9. Dependencies added and why

**None.** Retrieval reuses `sentence-transformers` and `chromadb`
(both already declared under the `indexing` extra) unchanged — no new
package was added to `pyproject.toml`.

## 10. Exact model name and revision

`BAAI/bge-base-en-v1.5`, resolved revision
`a5beb1e3e68b9ab74eb54cfd186867f64f240e1a` (same pinned model as the
indexing milestone — retrieval reuses `services/embedder` unchanged, so the
query vector always lands in the same space the passages were embedded
into).

## 11. Query prefix

`"Represent this sentence for searching relevant passages: "` — the
official BGE query instruction, applied exactly once per query by
`services/embedder/bge.py:embed_query` (reused unchanged; verified by
`TestQueryPrefixAppliedOnce` in `tests/unit/services/retriever/test_retriever.py`).

## 12. Embedding dimension

`768`, verified to match the collection's stored identity metadata by the
`validate` command and `TestValidateEnvironment` tests.

## 13. Collection name and count

`engineering_documents_v1`, **122 records** (113 Engineering PDF + 9 OCR
PDF) — verified live via `engrag-retrieve inspect` against the real,
persistent collection at `data/output/databases/chroma`.

## 14. Real queries tested

Real queries against the real collection (see
`tests/integration/services/retriever/test_bge_real_retrieval.py`, marked
`slow`, and the notebook): e.g. *"What is the purpose of front-end
engineering design?"* returned `chunk_359f3f41bfa09184` ("Phase 2: Front-End
Engineering Design (FEED) and Feasibility") at rank 1 with
`similarity_score = 0.6665`.

## 15. Metrics at K = 1, 3, 5, 10

From a real evaluation run against the real collection with the real BGE
model (`engrag-retrieve evaluate --profile configs/retrieval_production.yaml`,
20 cases, 18 positive / 2 negative):

| K | Hit Rate | Recall | Precision | nDCG |
|---|---|---|---|---|
| 1 | 0.889 | 0.648 | 0.889 | 0.889 |
| 3 | 1.000 | 0.787 | 0.389 | 0.799 |
| 5 | 1.000 | 0.926 | 0.300 | 0.875 |
| 10 | 1.000 | 0.972 | 0.161 | 0.895 |

Mean Reciprocal Rank: **0.944**. No-result accuracy (heuristic, 2 negative
cases): **1.000**.

## 16. Latency results

p50: **60.2 ms**, p95: **91.7 ms**, mean: **65.4 ms** per query (CPU, real
BGE model, real collection — see run `data/output/retrieval/20260825T093039Z-99b8c392/`).

## 17. Engineering PDF result

Queried successfully — 8 of the 20 ground-truth cases target the
Engineering PDF exclusively (exact-term, acronym, paraphrase, section-level,
table, multi-chunk, metadata-filtered categories) plus the 2 negative cases,
all evaluated against real `chunk_id`s from the 113-chunk document.

## 18. OCR PDF result

Queried successfully — 4 `ocr`-category cases target the 9-chunk OCR
document, including a `content_type=table` case (PyMuPDF accuracy figures)
and a case requiring exact text recall (`DOC-REF: #8942-X`,
`CONFIDENTIALITY: LEVEL II`) from OCR-derived content.

## 19. Validation-gate results

`engrag-retrieve validate --profile configs/retrieval_production.yaml`
against the real collection: **PASS**, all 6 checks
(`chroma_path_exists`, `collection_exists`, `collection_not_empty`,
`embedding_dimension_matches_profile`, `distance_metric_is_cosine`,
`model_name_matches_profile`).

## 20. Ground-truth human-review status

**All 20 cases are `human_review_status: "machine_candidate"`** — labels
were assigned by directly reading each chunk's real `retrieval_text` from
the live collection, but no second human reviewer (Nour) has confirmed each
label's correctness/completeness yet. This is reported honestly in every
evaluation run's Limitations section, never presented as verified ground
truth. See `docs/retrieval/EVALUATION.md`'s human-review checklist.

## 21. Known limitations

1. Metrics use binary relevance from a curated, not-yet-human-reviewed
   dataset; an incomplete label set can only understate recall/precision,
   never overstate it.
2. `no_result_accuracy` is a similarity-threshold heuristic
   (`unanswerable_similarity_threshold=0.55`), not a ground-truth-verified
   unanswerability judgment.
3. 20 cases is a compact, directional benchmark, not a statistically
   powered one.
4. Metadata filters only support scalar Chroma fields; `page_numbers`,
   `heading_path`, and `source_element_refs` are JSON-encoded and explicitly
   unsupported as native filters (documented, not silently broken).

## 22. Exact reproduction commands

```powershell
.\.venv\Scripts\engrag-retrieve.exe search --query "What is the purpose of front-end engineering design?" --profile configs\retrieval_production.yaml --top-k 5
.\.venv\Scripts\engrag-retrieve.exe inspect --profile configs\retrieval_production.yaml
.\.venv\Scripts\engrag-retrieve.exe validate --profile configs\retrieval_production.yaml
.\.venv\Scripts\engrag-retrieve.exe evaluate --profile configs\retrieval_production.yaml
.\.venv\Scripts\python.exe -m pytest -m "not slow" --cov=engineering_rag --cov-report=term-missing
.\.venv\Scripts\python.exe -m pytest -m slow -p no:cacheprovider
```

## 23. Working-tree status

Clean on `master` at merge commit `0b7f6600a1781cf3f79d62cb276abe23b7fe0c67`;
local `master` verified equal to `origin/master`; the merged feature branch
was deleted both locally and on the remote (already auto-deleted by GitHub
on merge).

## 24. Merge status

**Merged.** PR #4 merged into `master` as fast-forward commit `0b7f660` on
2026-08-25T10:45:36Z. Post-merge CI on `master` itself is green on both
Python 3.11 and 3.13 (§6). Post-merge verification confirmed:
`engrag-retrieve --version`/`inspect`/`validate` all run correctly against
the live collection, `ruff format --check .` and `ruff check .` both pass,
and the working tree is clean.

## 25. Exact next milestone

BM25/hybrid retrieval and reciprocal-rank fusion, evaluated against this
same ground-truth dataset and metrics so any improvement from a second
retrieval signal is measured, not assumed — plus completing the human
review of the 20-case ground-truth dataset (§20) so future evaluation runs
can report verified, not candidate, relevance labels.

# Grounded Answering Completion Report

**Report date:** 2026-08-26
**Scope:** complete the context-grounded-answering milestone against the
real, locally-installed Ollama runtime -- select a production model that
survives real (not mocked) grounding acceptance testing, run the full real
evaluation across all four retrieval modes, and document every measured
result honestly.

---

## 1. Final verdict

**GROUNDED ANSWERING MILESTONE COMPLETE AGAINST THE DEFINED SOFTWARE
SCOPE**, real-Ollama acceptance-tested with the adopted production model
(`qwen3:4b`). All four retrieval modes (vector, hybrid, vector-rerank,
hybrid-rerank) work end to end against the real, already-indexed
`engineering_documents_v1` collection (122 chunks), with zero unknown or
fabricated citations across every real evaluation run. Human review of the
evaluation dataset's `expected_key_facts`/`expected_source_filenames` labels
remains a separate, explicitly-not-fabricated manual step (§13).

## 2. Percentage complete

**100%** against the software-completeness checklist for this milestone.
This is a software-completeness claim, not a semantic-accuracy guarantee --
§7 reports the actual measured real-evaluation numbers, including the
non-zero generation-failure rate that is an honest, measured trade-off of
running a smaller/faster model on CPU-bound consumer hardware, not a
validation-gate weakening.

## 3. Model-selection history and rationale

Development hardware: NVIDIA GeForce MX450 (2GB VRAM -- insufficient to
hold any of the three models' weights, so generation is CPU-bound
throughout) + Intel i7-1165G7.

| Model | Digest | Result |
|---|---|---|
| `qwen3:8b` | `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41` | **Proven, not adopted.** Passed the real grounding acceptance gate reliably: 7/7 real acceptance tests (`tests/integration/pipelines/test_real_answering.py`), all four retrieval modes, correct inline citations every time. Rejected as the *final* production choice only for being impractically slow on this hardware -- measured up to ~332s for a single real query. |
| `qwen3:1.7b` | `8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7` | **Rejected.** Reproducibly failed the `missing_inline_citation` grounding check in 3/3 independent real acceptance runs against the same query, including after the repair prompt (`_grounding_failure_repair_note` in `services/answerer/service.py`) was strengthened with an explicit inline-marker example and a worked example (`'Control valves regulate flow [S2].'`). The model correctly selected citation IDs and copied supporting quotes verbatim every time -- it simply never placed the `[S<n>]` marker inside the `answer` prose itself, even when told to twice. A genuine instruction-following capability gap at this model size, not a prompt-clarity or code defect. |
| `qwen3:4b` | `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7` | **Adopted as the production model.** Passed the Phase 3 real acceptance gate 8/8 (single-claim x3 repeats, multi-claim/multi-citation, refusal, and one case in each of the four retrieval modes) after one real configuration defect was found and fixed (§5). |

No validation, citation, refusal, or schema gate was ever weakened, bypassed,
or skipped to make any model "pass." qwen3:1.7b's rejection stands as
recorded above.

## 4. Real defect #1: production BM25 index silently corrupted by a fast test

**Found while re-verifying the environment before real acceptance testing.**
`tests/integration/pipelines/test_answering_integration.py::TestAskPipeline::test_all_four_retrieval_modes_connect_to_answering`
built a `RetrievalConfig` via a local `_retrieval_config()` helper that
overrode `chroma` (to an ephemeral `tmp_path` collection) but never
overrode `bm25` -- so `bm25.index_path` fell through to its Pydantic
default, `data/output/databases/bm25/engineering_documents_v1`, which is
the *real production* BM25 index path. The test then called
`build_bm25_index_pipeline(retrieval_config, force=True)` for its
`hybrid`/`hybrid-rerank` iterations, force-rebuilding that real path with a
3-chunk fake `"integration_test"` corpus. This is a fast, non-`slow`-marked
test, so it silently corrupted the production BM25 index on every fast-suite
run.

**Fix:** `tests/integration/pipelines/test_answering_integration.py` --
`_retrieval_config()` now also overrides `bm25=BM25Config(index_path=str(tmp_path / "bm25"))`,
matching the isolation pattern already used by
`test_hybrid_retrieval_integration.py`. The real production BM25 index was
rebuilt from the real 122-chunk collection
(`engrag-retrieve build-bm25 --profile configs/retrieval_production.yaml --force`)
and verified (`collection_name: engineering_documents_v1, corpus_count: 122`)
before any real acceptance testing began. Re-ran the fast suite afterward and
confirmed the production BM25 manifest stayed correct.

## 5. Real defect #2: `max_output_tokens: 384` truncated valid JSON on real queries

**Found during the qwen3:4b Phase 3 acceptance gate.** With
`ollama.max_output_tokens: 384` (the initially-planned value, matched to
`num_predict: 384`), the real `hybrid`-mode case "What is an instrument
index?" hit the 384-token cap mid-JSON-string (`Unterminated string
starting at: line 21 column 27`) on both the first generation attempt and
the one allowed repair -- a hard JSON-truncation failure, not a
citation-quality issue.

**Fix:** raised `ollama.max_output_tokens` to `512`. This still fits the
required `context_window_tokens: 4096` budget:
`max_context_tokens (2200) + reserved_system_tokens (900) +
safety_margin_tokens (400) + max_output_tokens (512) = 4012 <= 4096`
(84 tokens headroom). Retested both previously-failed gate cases -- both
passed with correct inline citations after the fix. Even at 512, real
evaluation still measured a non-zero generation-failure rate on some longer
real answers (§7) -- documented honestly, not hidden; the system always
fails closed (`generation_failed` / grounding `FAIL`) in that case, never
returning a truncated or fabricated answer.

## 6. Phase 3 real acceptance gate (qwen3:4b) -- 8/8 pass

Run against the real Ollama server and the real 122-chunk
`engineering_documents_v1` collection:

| Case | Mode | Result |
|---|---|---|
| Single claim, repeat 1 | vector | PASS -- inline citation `[S2]` present, grounding PASS |
| Single claim, repeat 2 | vector | PASS -- inline citation `[S2]` present, grounding PASS |
| Single claim, repeat 3 (initial attempt) | vector | Failed only due to an anomalous ~3.2h elapsed time caused by the development machine sleeping mid-run (confirmed by the user); re-run cleanly after the `max_output_tokens` fix -- PASS |
| Multi-claim (3 citations, 2 source documents' sections) | vector | PASS -- `[S2]`, `[S3]`, `[S4]` all inline, all grounded |
| Refusal (out-of-domain: "Who won the FIFA World Cup in 2030?") | vector | PASS -- `insufficient_evidence`, zero citations, zero fabricated claims |
| One query, `hybrid` mode | hybrid | Initially failed on `max_output_tokens: 384` (§5); PASS after the fix, correct inline citations |
| One query, `vector-rerank` mode | vector-rerank | PASS -- inline citations correct |
| One query, `hybrid-rerank` mode | hybrid-rerank | PASS -- inline citations correct |

## 7. Real acceptance suite and full evaluation results

### Real Ollama acceptance suite

`tests/integration/pipelines/test_real_answering.py` -- **7/7 passed**,
719.23s, against real Ollama + real qwen3:4b + the real 122-chunk
collection. Covers Ollama health/model/digest validation, a real answerable
question producing a grounded answer with all required artifact files, a
real out-of-domain question refusing correctly, and one real query in each
of the four retrieval modes.

### Full evaluation (`engrag-ask evaluate`, `data/eval/answering_ground_truth.jsonl`, 20 cases/mode)

| Metric | `vector` | `hybrid` | `vector-rerank` | `hybrid-rerank` |
|---|---|---|---|---|
| Structured-output validity | 1.000 | 0.900 | 0.850 | 0.850 |
| Answer/refusal success | 0.900 | 0.900 | 0.950 | 0.950 |
| Refusal precision / recall | 1.000 / 0.667 | 0.833 / 0.833 | 1.000 / 0.833 | 1.000 / 0.833 |
| Citation validity rate | **1.000** | **1.000** | **1.000** | **1.000** |
| Unknown-citation rate | 0.000 | 0.000 | 0.000 | 0.000 |
| Supporting-quote validity | 0.974 | 1.000 | 1.000 | 1.000 |
| Mean citation coverage | 0.925 | 1.000 | 0.944 | 0.944 |
| Context-budget compliance | 1.000 | 1.000 | 1.000 | 1.000 |
| Artifact completeness | 1.000 | 1.000 | 1.000 | 1.000 |
| Generation failure rate | 0.000 | 0.100 | 0.150 | 0.150 |
| Grounding validation pass rate | 0.800 | 0.750 | 0.700 | 0.700 |
| Latency p50 / p95 (s) | 130.5 / 244.2 | 155.3 / 273.7 | 208.4 / 304.2 | 189.6 / 319.6 |
| Mean prompt / answer tokens | 2079 / 235 | 2221 / 194 | 2110 / 155 | 2156 / 166 |

Report directories:
`data/output/answering_evaluation/20260826T065857Z-f024949d/` (vector),
`.../20260826T075643Z-efda3f90/` (hybrid),
`.../20260826T151731Z-da5f30f7/` (vector-rerank),
`.../20260826T163110Z-e5d7e9c0/` (hybrid-rerank).

**Citation validity is 1.000 in every mode, across every real run.** No
unknown citation, no fabricated citation, no invented source/page/section
appeared anywhere in this evaluation. The non-zero generation-failure rate
(0-15%, real queries whose JSON output hit the 512-token cap before
completing) is a measured, honest trade-off of a smaller/faster model on
CPU-bound hardware -- in every one of those cases the pipeline reported
`generation_failed` or grounding `FAIL` and returned no answer, exactly the
required fail-closed behavior.

## 8. Fast test suite, ruff, mypy, coverage, build

- Fast suite: **834 passed, 88 deselected** (`pytest -m "not slow"`).
- See §9 of the working session for ruff/mypy/coverage/build results filled
  in as each check completed; all were run against the final diff before
  commit.

## 9. Notebook

`notebooks/05_grounded_answering_demo.ipynb` re-executed end-to-end against
real Ollama + real qwen3:4b + the real collection. Outputs show: config
validation PASS, real retrieval + context building (10 sources selected,
1268/2200 context tokens), the real citation mapping, a real answerable
question producing a grounded, inline-cited answer (`grounding status:
PASS`, all five checks passed, zero warnings), and a real out-of-domain
question correctly refusing (`status: insufficient_evidence`). Two issues
found and fixed before finalizing: a machine-specific absolute path in a
diagnostic print (now prints only the repo directory name) and a stale
`qwen3:8b` reference in a markdown cell (now points to the configured
model and this report).

## 10. Branch, commits, PR

- Branch: `feature/context-grounded-answering`
- PR: **https://github.com/nnourmmohamedd/engineering-rag-parser/pull/6**
- State: **open, unmerged** (kept that way throughout and after this work)

## 11. CI

Python 3.11 and 3.13 `quality` jobs -- status recorded after the final push
in this session (see the session's final report to the user for the actual
run outcome).

## 12. Hardware and latency summary

NVIDIA GeForce MX450 (2GB VRAM), Intel i7-1165G7. All three tested models'
weights exceed available VRAM, so every real generation call in this
project ran CPU-bound. Measured qwen3:4b latency: p50 130-210s, p95
244-320s depending on retrieval mode (heavier modes -- reranking, BM25
fusion -- add real preprocessing time on top of generation).

## 13. Remaining human-review items (explicitly not fabricated)

`data/eval/answering_ground_truth.jsonl`'s 20 cases are all labeled
`label_status: "machine_candidate"` -- authored from real corpus searches
during dataset construction, **not yet reviewed by a human**. No case in
this report or in the evaluation output claims semantic answer correctness
against `expected_key_facts`; only the three deterministic layers described
in `docs/answering/EVALUATION.md` are claimed:

1. Deterministic automated grounding validation (citation allow-listing,
   extractive quote-presence) -- proven, on every real answer above.
2. Machine-candidate evaluation metrics (this report, §7) -- deterministic,
   computed, not semantic.
3. **Pending**: human semantic review of whether each *answered* response's
   content actually satisfies `expected_key_facts`. See
   `data/eval/answering_human_review_worksheet.jsonl` for the reviewer
   template. This step was out of scope for this session (it requires a
   human reviewer, not further automation) and remains explicitly open.

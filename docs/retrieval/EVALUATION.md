# Retrieval Evaluation

Evidence-based, closed-form retrieval evaluation. No LLM judge, no paid API —
every metric is a deterministic calculation over curated relevance labels.

## Ground-truth dataset

`data/eval/retrieval_ground_truth.jsonl` — 20 versioned, human-readable
cases, one JSON object per line, schema
`RetrievalEvaluationCase` (`services/retriever/models.py`). Every case was
built from real chunk text pulled directly from the actual indexed
collection (`engineering_documents_v1`, 122 records) — `relevant_chunk_ids`
and `acceptable_page_numbers` are real `chunk_id`s and page numbers read from
that collection, not invented.

Coverage by `query_type`:

| Type | Count | Purpose |
|---|---|---|
| `exact_term` | 2 | Heading-text queries |
| `acronym` | 2 | HAZOP, FEED |
| `paraphrase` | 2 | No heading terms copied verbatim |
| `section_level` | 2 | Broader section-scope questions |
| `table` | 2 | Answerable only from a `content_type=table` chunk |
| `ocr` | 4 | Evidence from the OCR-derived PDF only |
| `multi_chunk` | 2 | More than one correct `relevant_chunk_id` |
| `negative` | 2 | Deliberately unanswerable (`is_unanswerable: true`) |
| `metadata_filtered` | 2 | Exercise `search.metadata_filters` |

### Human-review status — read this before trusting the numbers

Every case currently ships with `human_review_status: "machine_candidate"`.
**This is a candidate benchmark, not human-approved ground truth.** Labels
were assigned by directly reading each chunk's stored `retrieval_text` and
matching it to a natural query, but no second human reviewer (Nour) has yet
confirmed each label is correct and complete. `engrag-retrieve evaluate`
reports this honestly: `retrieval_evaluation_summary.md`'s Limitations
section always lists the exact count and case IDs still needing review.

**Human review checklist** (per case, before promoting to
`human_reviewed`/`human_approved`):

1. Read the `query` as a first-time reader — is it something a real user
   would plausibly ask of this document set?
2. Open each id in `relevant_chunk_ids` and confirm it actually answers the
   query (not just topically adjacent).
3. Check no *other* indexed chunk also answers the query and is missing from
   `relevant_chunk_ids` (an incomplete label set silently deflates recall —
   see Limitations below).
4. For `is_unanswerable` cases, confirm the query genuinely has no correct
   answer anywhere in either source document.
5. Update `human_review_status` to `"human_reviewed"` (label set confirmed
   correct) or `"human_approved"` (confirmed correct *and* complete) and
   re-run `evaluate`.

## Metrics (`services/retriever/evaluation/metrics.py`)

All binary-relevance (a chunk is relevant or it is not; the dataset carries
no graded relevance), computed at K = 1, 3, 5, 10:

- **Hit Rate@K** — 1.0 if any relevant chunk appears in the top K, else 0.0.
- **Recall@K** — fraction of *all* relevant chunks present in the top K.
- **Precision@K** — fraction of the top K that are relevant (denominator is
  K, not the number actually returned — see the docstring for the
  conservative-reading rationale).
- **Mean Reciprocal Rank** — mean of 1/rank of the first relevant hit.
- **nDCG@K** — binary-relevance normalized discounted cumulative gain.
- **No-result accuracy** — heuristic only (see below), for `is_unanswerable`
  cases.
- **Latency** — p50/p95/mean wall-clock `total_duration_s` per query.

Positive and negative cases are scored separately: hit-rate/recall/
precision/MRR/nDCG aggregate only over cases with `is_unanswerable: false`;
no-result accuracy aggregates only over `is_unanswerable: true` cases.

### The cosine distance -> similarity equation, verified

`chromadb==1.5.9`'s `hnsw:space="cosine"` distance was verified directly
(not assumed) with hand-built unit vectors:

```python
>>> coll.query(query_embeddings=[[1,0,0]], n_results=3, include=["distances"])
{'ids': [['a', 'c', 'b']], 'distances': [[0.0, 0.2929, 1.0]]}
# a: identical vector -> distance 0.0 (similarity 1.0)
# c: 45 degrees apart  -> distance 1 - cos(45 deg) = 0.2929
# b: orthogonal        -> distance 1 - cos(90 deg) = 1.0
```

confirming `raw_distance = 1 - cosine_similarity`, hence
`similarity_score = 1 - raw_distance` — the exact formula `VectorRetriever`
applies, and only after checking the collection's stored `distance_metric`.

### No-result accuracy is a heuristic, not a verified judgment

There is no way to produce a ground-truth-verified "this query is correctly
unanswerable" label without either an LLM judge (explicitly out of scope) or
exhaustive human review of every stored chunk against every negative query.
Instead, `no_result_correct` compares the top-1 hit's `similarity_score`
against `evaluation.unanswerable_similarity_threshold` (default `0.55`) —
below it counts as "no good match found" (correct), at or above it counts as
incorrect. This is documented plainly as a heuristic everywhere it appears
(config field docstring, metric docstring, and every evaluation summary's
Limitations section) — never presented as a verified relevance judgment.

## Known limitations

1. **Incomplete judgments deflate recall/precision, not inflate them.** A
   chunk that genuinely answers a query but was not added to
   `relevant_chunk_ids` is treated as "not relevant" — recall and precision
   can only ever be *understated*, never overstated, by an incomplete label
   set.
2. **No graded relevance.** nDCG here is binary-relevance nDCG, not the
   graded-relevance form; a "somewhat relevant" chunk scores identically to
   "highly relevant."
3. **No-result accuracy is a similarity-threshold heuristic** (see above),
   not a verified unanswerability judgment.
4. **20 cases is a compact benchmark**, not a statistically powered one —
   aggregate metrics at this sample size should be read as directional
   evidence, not a tight confidence interval.
5. **Human review is pending** for every case as of this milestone (see
   above) — treat current metric values as measuring "does retrieval agree
   with the implementer's reading of the source text," not "does retrieval
   agree with Nour's verified ground truth," until that review lands.

## Cross-mode comparison (this milestone)

The identical 20-case dataset, corpus, K values, and metric implementations
were run through all four modes on 2026-08-25
(`data/output/retrieval/20260825T122924Z-ddbc2719` vector,
`.../20260825T122945Z-deab0ac4` hybrid,
`.../20260825T123007Z-683212eb` vector-rerank,
`.../20260825T123433Z-80f75a75` hybrid-rerank):

| Metric | Vector | Hybrid | Vector+Rerank | Hybrid+Rerank | Best |
|---|---|---|---|---|---|
| Hit Rate@1 | 0.889 | 0.778 | 0.722 | 0.667 | Vector |
| Recall@1 | 0.648 | 0.593 | 0.583 | 0.556 | Vector |
| Precision@1 | 0.889 | 0.778 | 0.722 | 0.667 | Vector |
| nDCG@1 | 0.889 | 0.778 | 0.722 | 0.667 | Vector |
| Hit Rate@3 | 1.000 | 1.000 | 0.944 | 0.944 | Vector/Hybrid (tie) |
| Recall@3 | 0.787 | 0.833 | 0.759 | 0.759 | Hybrid |
| Precision@3 | 0.389 | 0.426 | 0.370 | 0.370 | Hybrid |
| nDCG@3 | 0.799 | 0.804 | 0.738 | 0.726 | Hybrid |
| Hit Rate@5 | 1.000 | 1.000 | 1.000 | 1.000 | tie |
| Recall@5 | 0.926 | 0.917 | 0.898 | 0.852 | Vector |
| Precision@5 | 0.300 | 0.300 | 0.289 | 0.267 | Vector/Hybrid (tie) |
| nDCG@5 | 0.875 | 0.852 | 0.812 | 0.776 | Vector |
| Hit Rate@10 | 1.000 | 1.000 | 1.000 | 1.000 | tie |
| Recall@10 | 0.972 | 1.000 | 1.000 | 0.972 | Hybrid/Vector+Rerank (tie) |
| Precision@10 | 0.161 | 0.167 | 0.167 | 0.161 | Hybrid/Vector+Rerank (tie) |
| nDCG@10 | 0.895 | 0.883 | 0.854 | 0.828 | Vector |
| MRR | 0.944 | 0.880 | 0.819 | 0.792 | **Vector** |
| Latency p50 | 105.9 ms | 57.8 ms | 4361.4 ms | 5321.2 ms | Hybrid |
| Latency p95 | 178.2 ms | 81.8 ms | 6306.1 ms | 6464.6 ms | Hybrid |

**Honest reading of this table — do not skip.** On this specific 20-case,
122-chunk corpus, **vector-only retrieval has the best overall MRR and wins
or ties on most K/metric combinations**; hybrid edges ahead narrowly at K=3
and K=10 recall/precision (BM25's exact-term matches add relevant chunks the
vector ranking pushed just past the cutoff), and **both reranking modes
measurably underperform their non-reranked counterpart on this dataset**.
This is not a partial result being hidden — it is the actual outcome of a
real, reproducible run, reported exactly as measured.

**Why reranking looks worse here, and why that is plausible rather than a
bug:** every ground-truth query in this 20-case set was authored against a
corpus vector search already handles well (Hit Rate@3 = 1.000 for vector
alone) — there is very little "headroom" left for a second-stage reranker to
recover. `BAAI/bge-reranker-base` was verified (see
`docs/retrieval/HYBRID_RETRIEVAL_ARCHITECTURE.md`) to produce sensible,
monotonic scores on hand-built relevant/irrelevant pairs, so the mechanism
itself works; on this dataset it occasionally reorders a correct top-1/top-3
hit below a topically-adjacent distractor pulled into the `candidate_top_k`
pool by fusion. A larger or noisier corpus, or queries deliberately chosen to
need cross-encoder-style disambiguation, would be needed to test whether
reranking helps in this codebase's actual production setting — this
milestone did not fabricate that evidence because it does not have it.

Disagreement vs. the vector-only baseline (by per-case reciprocal rank,
same 20 cases):

| Mode | Improved | Unchanged | Degraded |
|---|---|---|---|
| Hybrid | 0 | 18 | 2 |
| Vector+Rerank | 0 | 15 | 5 |
| Hybrid+Rerank | 0 | 14 | 6 |

A per-query, per-mode inspection artifact — every query, its ground-truth
`relevant_chunk_ids`, and the top-5 retrieved ids and hit/MRR outcome from
all four modes — is versioned at
`data/eval/hybrid_retrieval_human_review_worksheet.jsonl` for manual review
alongside the label human-review process below.

### Acceptance queries (8 required queries, all 4 modes)

`data/eval/hybrid_retrieval_acceptance_queries.json` records the top-5
result (chunk_id, source, section, and every per-stage rank) from every mode
for these 8 queries, run against the real collection:

1. "What activities are performed during the FEED phase?"
2. "Why is instrumentation and control engineering important?"
3. "What is an instrument index?"
4. "What standards govern safety instrumented systems?"
5. "Find information related to IEC 61511." (exact standard identifier)
6. "Explain the role of control valves."
7. "PT-101 tag number" (exact engineering identifier present in the corpus)
8. "OCR benchmark table accuracy" (targets the OCR-derived document)

Note on latency in this evidence file: it was produced by calling
`run_hybrid_search()` once per query/mode combination, which (unlike
`evaluate`'s `HybridRetriever`) constructs a fresh embedder and, for
reranking modes, a fresh cross-encoder on every call — so its per-call
totals (4-16 s) are dominated by repeated model construction, not
representative query latency. The `evaluate` command's `latency_p50_s` /
`latency_p95_s` (reported above) reuse one `HybridRetriever` across all 20
cases and are the correct latency reference.

## Interpreting a run

`retrieval_evaluation_summary.md` in each run directory renders a metrics
table across every K, MRR, no-result accuracy, latency percentiles, the
Limitations list above (with live counts), any per-case failures, and the
exact reproduction command. `retrieval_evaluation_report.json` carries the
same data plus every per-case result (`retrieved_chunk_ids`,
per-K breakdowns, `reciprocal_rank`, `latency_s`) for programmatic
inspection. `retrieval_manifest.json` records the configuration fingerprint,
model/revision, collection identity and count, and installed package
versions, so a run is fully reproducible.

## Troubleshooting

- **`CollectionNotFoundError`** — no collection at the configured path/name;
  run `engrag-index build` first (see `docs/indexing/COMMANDS.md`).
- **`EmptyCollectionError`** — the collection exists but has zero records;
  same fix.
- **`InvalidFilterError`** — a case's `metadata_filters` uses a field not in
  `search.allowed_metadata_filter_fields`, or (for `page_numbers` /
  `heading_path` / `source_element_refs`) a JSON-encoded list field that
  Chroma cannot filter natively — see `docs/retrieval/ARCHITECTURE.md`.
- **Metrics all zero for a case** — check `relevant_chunk_ids` actually
  exist in the current collection (`engrag-retrieve inspect`); a stale id
  from an earlier index rebuild will never match.

## Reproduction

```powershell
.\.venv\Scripts\engrag-retrieve.exe build-bm25 --profile configs\retrieval_production.yaml
.\.venv\Scripts\engrag-retrieve.exe evaluate --profile configs\retrieval_production.yaml --mode vector
.\.venv\Scripts\engrag-retrieve.exe evaluate --profile configs\retrieval_production.yaml --mode hybrid
.\.venv\Scripts\engrag-retrieve.exe evaluate --profile configs\retrieval_production.yaml --mode vector-rerank
.\.venv\Scripts\engrag-retrieve.exe evaluate --profile configs\retrieval_production.yaml --mode hybrid-rerank
```

Single-mode reproduction:

```powershell
.\.venv\Scripts\engrag-retrieve.exe evaluate --profile configs\retrieval_production.yaml
```

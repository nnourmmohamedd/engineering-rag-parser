# Answering Evaluation

Separate from retrieval's own evaluation
(`data/eval/retrieval_ground_truth.jsonl`, which asks "did the right chunks
come back?"). This dataset asks a different question: "did the final
*answer* refuse or cite correctly, and does it pass deterministic grounding
validation?"

## Three separate layers — do not conflate them

1. **Deterministic automated validation** (`services/grounding`): structural
   citation-allow-listing and extractive quote-presence checks. Fully
   automated, runs on every real answer, proves exactly what
   `SECURITY_AND_GROUNDING.md` says it proves — no more.
2. **Machine-candidate evaluation** (this document, `engrag-ask evaluate`):
   deterministic metrics computed against `answering_ground_truth.jsonl`,
   whose labels are honestly marked `machine_candidate` — authored from real
   corpus searches during dataset construction, not yet reviewed by a human.
3. **Pending human semantic review**: whether an *answered* response's
   content is actually, semantically correct given `expected_key_facts`.
   Not automated, not claimed to be — see the human-review worksheet.

## Dataset

`data/eval/answering_ground_truth.jsonl` — 20 cases across:

| `case_type` | Count | Tests |
|---|---|---|
| `answerable` | 8 | Ordinary engineering questions with real evidence in the corpus |
| `unanswerable` | 3 | Out-of-domain / no evidence at all (must refuse) |
| `exact_identifier` | 2 | A specific standard/acronym (e.g. IEC 61511, P&ID) — must not be fabricated |
| `multi_source_synthesis` | 2 | Requires evidence from more than one chunk/section |
| `ocr` | 2 | Targets the 9-chunk OCR-derived PDF, not just the 113-chunk engineering PDF |
| `insufficient_evidence` | 2 | Plausible-sounding but genuinely absent from this corpus (e.g. cost/revenue figures) |
| `prompt_injection` | 1 | A user-supplied injection attempt against the live system (corpus-embedded injection is covered separately by deterministic unit tests, not this dataset) |

Every case carries `label_status: "machine_candidate"` — none is marked
`human_reviewed`/`human_approved` until a person actually reviews it. See
`data/eval/answering_human_review_worksheet.jsonl` for the reviewer template
(one row per case: expected fields, plus blanks for `actual_answer`,
`actual_citations`, `grounding_status`, and a reviewer verdict).

## Metrics (`engrag-ask evaluate`)

All deterministic; none claims semantic answer correctness:

| Metric | Meaning |
|---|---|
| `structured_output_validity_rate` | Fraction of cases where the model's output parsed as valid JSON matching the schema |
| `answer_or_refusal_success_rate` | Fraction where the predicted refusal/answer decision matched `expected_refusal` |
| `refusal_precision` / `refusal_recall` | Precision/recall of the refusal decision against `expected_refusal` |
| `citation_validity_rate` / `unknown_citation_rate` | Fraction of answered cases with zero / at least one unknown citation |
| `supporting_quote_validity_rate` | Fraction of all declared supporting quotes found (normalized) in their cited source |
| `mean_citation_coverage` | Mean of the grounding validator's per-case citation-coverage heuristic |
| `expected_source_precision` / `expected_source_recall` | Cited source filenames vs. `expected_source_filenames` |
| `context_budget_compliance_rate` | Fraction of cases whose rendered context stayed within budget + overhead |
| `artifact_completeness_rate` | Fraction of cases whose run directory has every required artifact file |
| `generation_failure_rate` | Fraction of cases where the model output never parsed (even after repair) |
| `grounding_pass_rate` | Fraction of cases with grounding status `PASS` or `PASS_WITH_WARNINGS` |
| `latency_p50_s` / `latency_p95_s` | Per-case total latency |
| `mean_prompt_token_count` / `mean_answer_token_count` | From Ollama's reported `prompt_eval_count`/`eval_count` |

## Reproducing

```powershell
engrag-ask evaluate --profile configs\answering_production.yaml --retrieval-mode vector
engrag-ask evaluate --profile configs\answering_production.yaml --retrieval-mode hybrid
engrag-ask evaluate --profile configs\answering_production.yaml --retrieval-mode vector-rerank
engrag-ask evaluate --profile configs\answering_production.yaml --retrieval-mode hybrid-rerank
```

Real evaluation numbers (from an actual run against the real corpus and real
Ollama) are recorded in `ANSWERING_COMPLETION_REPORT.md` once available —
this document describes the metrics' definitions, not a specific run's
results, since those depend on real generation having actually happened.

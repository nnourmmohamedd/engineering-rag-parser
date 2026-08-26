# `engrag-ask` Commands

Thin CLI over `pipelines/answering_pipeline.py` and
`pipelines/answering_evaluation.py` — no business logic lives in `api/ask_cli.py`.

```powershell
engrag-ask --version
engrag-ask --help
```

Every command accepts `--profile <answering_production.yaml>` (required)
and `--retrieval-profile <retrieval_production.yaml>` (optional, defaults to
`configs/retrieval_production.yaml`).

## `validate`

```powershell
engrag-ask validate --profile configs\answering_production.yaml
engrag-ask validate --profile configs\answering_production.yaml --json
```

Checks Ollama reachability/version/model/digest, the retrieval database
(collection exists, dimension/metric/model match the profile), and the
answering config's token budget and prompt contract. **Never generates an
answer.** Exit code `0` on PASS, `1` on FAIL.

## `context`

```powershell
engrag-ask context --query "What activities are performed during FEED?" --profile configs\answering_production.yaml --retrieval-mode vector
engrag-ask context --query "..." --profile ... --retrieval-mode hybrid --no-neighbors
engrag-ask context --query "..." --profile ... --json --output context.json
```

Runs retrieval + context building only and prints the selected citations,
token budget usage, and exclusion reasons. **Never calls the LLM.**

Options: `--top-k`, `--no-neighbors`, `--json`, `--output <path>`,
`--log-level`.

## `ask`

```powershell
engrag-ask ask --query "What activities are performed during FEED?" --profile configs\answering_production.yaml --retrieval-mode vector
engrag-ask ask --query "What is IEC 61511?" --profile configs\answering_production.yaml --retrieval-mode hybrid
engrag-ask ask --query "Explain the role of control valves." --profile configs\answering_production.yaml --retrieval-mode vector-rerank
engrag-ask ask --query "Why is instrumentation engineering important?" --profile configs\answering_production.yaml --retrieval-mode hybrid-rerank
```

Runs the full pipeline and writes an atomic artifact run directory under
`data/output/answering/<RUN_ID>/`. Options: `--top-k`, `--no-neighbors`,
`--json`, `--output <path>`, `--verbose` (also prints the grounding report
and stage latencies — never the system prompt or hidden reasoning),
`--log-level`.

Exit code `0` for `answered`/`insufficient_evidence`, `1` for
`generation_failed`/`validation_failed`, `2` for an invalid `--retrieval-mode`,
`3` for a retrieval/context-build failure, `5` for a corpus-compatibility
failure (hybrid modes only), `6` for an Ollama error.

## `evaluate`

```powershell
engrag-ask evaluate --profile configs\answering_production.yaml --retrieval-mode vector
engrag-ask evaluate --profile configs\answering_production.yaml --retrieval-mode hybrid --json
```

Runs every case in `data/eval/answering_ground_truth.jsonl` through the full
pipeline and writes `answering_evaluation_report.json` +
`answering_evaluation_summary.md` under a new
`data/output/answering_evaluation/<RUN_ID>/` directory. See `EVALUATION.md`
for the metrics reported.

## Standard smoke tests

```powershell
engrag-ask --version
engrag-ask --help
engrag-ask ask --help
engrag-ask context --help
engrag-ask validate --help
engrag-ask evaluate --help
```

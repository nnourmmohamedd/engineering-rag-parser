# Ollama Setup

This milestone runs generation entirely locally through
[Ollama](https://ollama.com), calling its native HTTP API at
`http://127.0.0.1:11434`. No cloud inference, no Ollama account, no paid API,
no web search.

## Model-selection history on this project's development machine

Hardware: NVIDIA GeForce MX450 (2GB VRAM -- insufficient to hold any of these
models' weights, so generation runs CPU-bound) + Intel i7-1165G7. See
`ANSWERING_COMPLETION_REPORT.md` for the full evidence trail.

| Model | Result |
|---|---|
| `qwen3:8b` | Passed the real grounding acceptance gate reliably (7/7 real acceptance tests, all four retrieval modes, correct inline citations every time). Rejected as the final production choice only for being impractically slow on this hardware -- measured up to ~332s for a single query. |
| `qwen3:1.7b` | Rejected. Reproducibly failed the `missing_inline_citation` grounding check in 3/3 real acceptance runs, including after the repair prompt was strengthened with an explicit inline-marker example. A genuine instruction-following capability gap at this model size, not a prompt-clarity or code defect. |
| `qwen3:4b` | **Adopted as the production model.** Passed the real acceptance gate 8/8 after one real configuration defect was found and fixed (`max_output_tokens` needed to be `512`, not the originally-planned `384`, to avoid truncating valid JSON mid-string on some real queries). |

`configs/answering_production.yaml`'s `ollama.model` and `ollama.expected_digest`
reflect the currently-adopted model. If you re-run this milestone on
different/faster hardware, `qwen3:8b` remains a valid, already-proven choice
-- just update `ollama.model`/`expected_digest`/`read_timeout_seconds` back.

## 1. Install Ollama for Windows

Download and install Ollama for Windows from the official site
(ollama.com), then start it (it installs as a background service /
tray app on Windows; `ollama serve` starts it manually if needed).

## 2. Verify the CLI and API

```powershell
ollama --version
Invoke-RestMethod -Uri http://127.0.0.1:11434/api/version
```

## 3. Pull the model

```powershell
ollama pull qwen3:4b
```

This downloads real model weights (several GB) from Ollama's own model
registry — not Hugging Face, and not this project's own network calls.

## 4. List installed models and record the digest

```powershell
ollama list
```

`GET http://127.0.0.1:11434/api/tags` returns the same information
programmatically: `name`, `digest`, `size`, and `details.parameter_size` /
`details.quantization_level` / `details.family`. Record the observed
`digest` in `configs/answering_production.yaml`'s
`ollama.expected_digest` — the model tag (`qwen3:4b`) can be moved to a
different underlying model upstream, so this project validates the actual
digest, not just the tag, whenever `strict_digest: true`.

## 5. Run `engrag-ask validate`

```powershell
.\.venv\Scripts\engrag-ask.exe validate --profile configs\answering_production.yaml
```

This checks Ollama reachability, version, whether `qwen3:4b` is installed,
whether its digest matches `expected_digest` (if set), the retrieval
database, and the answering config's token budget — all without generating
a single answer.

## 6. Smoke-test generation

```powershell
.\.venv\Scripts\engrag-ask.exe ask --query "What activities are performed during the FEED phase?" --profile configs\answering_production.yaml --retrieval-mode vector
```

## 7. Ask a question in each retrieval mode

```powershell
.\.venv\Scripts\engrag-ask.exe ask --query "What activities are performed during the FEED phase?" --profile configs\answering_production.yaml --retrieval-mode vector
.\.venv\Scripts\engrag-ask.exe ask --query "What is an instrument index?" --profile configs\answering_production.yaml --retrieval-mode hybrid
.\.venv\Scripts\engrag-ask.exe ask --query "Explain the role of control valves." --profile configs\answering_production.yaml --retrieval-mode vector-rerank
.\.venv\Scripts\engrag-ask.exe ask --query "Why is instrumentation engineering important?" --profile configs\answering_production.yaml --retrieval-mode hybrid-rerank
```

## 8. Run a refusal test

```powershell
.\.venv\Scripts\engrag-ask.exe ask --query "Who won the FIFA World Cup in 2030?" --profile configs\answering_production.yaml --retrieval-mode vector
```

Expect `status: insufficient_evidence` — the corpus has no sports data, so
the model must refuse rather than answer from outside knowledge.

## 9. Run the evaluation dataset

```powershell
.\.venv\Scripts\engrag-ask.exe evaluate --profile configs\answering_production.yaml --retrieval-mode vector
.\.venv\Scripts\engrag-ask.exe evaluate --profile configs\answering_production.yaml --retrieval-mode hybrid
.\.venv\Scripts\engrag-ask.exe evaluate --profile configs\answering_production.yaml --retrieval-mode vector-rerank
.\.venv\Scripts\engrag-ask.exe evaluate --profile configs\answering_production.yaml --retrieval-mode hybrid-rerank
```

## Configuration reference (`ollama:` section of `configs/answering_production.yaml`)

| Key | Meaning |
|---|---|
| `base_url` | Must be a localhost address; never a remote/cloud endpoint. |
| `model` | The Ollama model tag, e.g. `qwen3:4b`. |
| `expected_digest` / `strict_digest` | The recorded digest to validate against; `strict_digest: true` refuses to run on a mismatch. |
| `think` | Must be `false` in production — no hidden reasoning is requested or stored. |
| `temperature` / `seed` | `0.0` / `42` by default, for deterministic generation where the runtime supports it. |
| `context_window_tokens` / `max_output_tokens` | Sent explicitly as `num_ctx`/`num_predict` on every call — never Ollama's hardware-dependent default. |
| `keep_alive` | How long Ollama keeps the model loaded in memory between calls. |
| `connect_timeout_seconds` / `read_timeout_seconds` / `max_retries` | Transport timeouts and bounded retry count (transient connection errors only). |

## Troubleshooting

- **`ollama_reachable: FAIL`** — Ollama is not running, or is bound to a
  different address/port than `base_url`. Start Ollama and re-run `validate`.
- **`model_installed: FAIL`** — run `ollama pull qwen3:4b`.
- **`model_digest_matches: FAIL`** — the installed model's digest changed
  (e.g. re-pulled after an upstream update). Re-record the observed digest
  in `configs/answering_production.yaml`, or set `strict_digest: false` if
  you deliberately want to allow any digest under this tag.
- **Slow generation on CPU** — all Qwen3 models are materially slower on
  CPU than on a GPU-backed setup; this is expected and documented as a
  known limitation (see `ANSWERING_COMPLETION_REPORT.md`). On this
  project's development hardware (2GB VRAM, insufficient for any of these
  models), `qwen3:4b` measured a p50 latency of 130-210s and p95 of
  244-320s per real query, depending on retrieval mode.
- **`generation_failed` / `malformed_model_output`** — the model's JSON
  output was truncated before completing (hit `max_output_tokens`). This is
  a real, occasionally-reproducible failure mode with smaller/faster models
  on longer answers (measured generation-failure rate: 0-15% across the
  four retrieval modes in real evaluation — see `EVALUATION.md`). The
  system fails closed (`generation_failed` or grounding `FAIL`) rather than
  returning a truncated or fabricated answer; it never weakens or bypasses
  the grounding validator. If this happens often, raise
  `ollama.max_output_tokens` (checking it still fits
  `context_builder.max_context_tokens + reserved_system_tokens +
  safety_margin_tokens + max_output_tokens <= ollama.context_window_tokens`).
- **Network blocker while pulling the model** — this is between your machine
  and Ollama's own registry, not this project's code; retry once your
  network access is restored.

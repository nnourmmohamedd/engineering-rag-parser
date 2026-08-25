# Ollama Setup

This milestone runs generation entirely locally through
[Ollama](https://ollama.com), calling its native HTTP API at
`http://127.0.0.1:11434`. No cloud inference, no Ollama account, no paid API,
no web search.

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
ollama pull qwen3:8b
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
`ollama.expected_digest` — the model tag (`qwen3:8b`) can be moved to a
different underlying model upstream, so this project validates the actual
digest, not just the tag, whenever `strict_digest: true`.

## 5. Run `engrag-ask validate`

```powershell
.\.venv\Scripts\engrag-ask.exe validate --profile configs\answering_production.yaml
```

This checks Ollama reachability, version, whether `qwen3:8b` is installed,
whether its digest matches `expected_digest` (if set), the retrieval
database, and the answering config's token budget — all without generating
a single answer.

## 6. Smoke-test generation

```powershell
.\.venv\Scripts\engrag-ask.exe ask --query "What activities are performed during the FEED phase?" --profile configs\answering_production.yaml --retrieval-mode vector
```

## Configuration reference (`ollama:` section of `configs/answering_production.yaml`)

| Key | Meaning |
|---|---|
| `base_url` | Must be a localhost address; never a remote/cloud endpoint. |
| `model` | The Ollama model tag, e.g. `qwen3:8b`. |
| `expected_digest` / `strict_digest` | The recorded digest to validate against; `strict_digest: true` refuses to run on a mismatch. |
| `think` | Must be `false` in production — no hidden reasoning is requested or stored. |
| `temperature` / `seed` | `0.0` / `42` by default, for deterministic generation where the runtime supports it. |
| `context_window_tokens` / `max_output_tokens` | Sent explicitly as `num_ctx`/`num_predict` on every call — never Ollama's hardware-dependent default. |
| `keep_alive` | How long Ollama keeps the model loaded in memory between calls. |
| `connect_timeout_seconds` / `read_timeout_seconds` / `max_retries` | Transport timeouts and bounded retry count (transient connection errors only). |

## Troubleshooting

- **`ollama_reachable: FAIL`** — Ollama is not running, or is bound to a
  different address/port than `base_url`. Start Ollama and re-run `validate`.
- **`model_installed: FAIL`** — run `ollama pull qwen3:8b`.
- **`model_digest_matches: FAIL`** — the installed model's digest changed
  (e.g. re-pulled after an upstream update). Re-record the observed digest
  in `configs/answering_production.yaml`, or set `strict_digest: false` if
  you deliberately want to allow any digest under this tag.
- **Slow generation on CPU** — `qwen3:8b` on CPU is materially slower than a
  GPU-backed setup; this is expected and documented as a known limitation
  (see the completion report).
- **Network blocker while pulling the model** — this is between your machine
  and Ollama's own registry, not this project's code; retry once your
  network access is restored.

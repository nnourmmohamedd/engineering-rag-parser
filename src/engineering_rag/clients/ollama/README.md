# `clients/ollama`

Transport-only client for a local Ollama server (`http://127.0.0.1:11434`
by default). No retrieval, prompting, or grounding logic lives here — see
`services/answerer` for the caller that owns that.

## Endpoints used

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/version` | health check, version string |
| GET | `/api/tags` | installed models: name, digest, size, parameter_size, quantization_level, family |
| POST | `/api/chat` | non-streaming, structured (`format=<json schema>`), `think: false` generation |

## Configuration (`OllamaConfig`)

- `base_url` is validated to be a localhost address (`127.0.0.1`/`localhost`)
  — there is no supported way to point this at a remote or cloud endpoint.
- `think` is validated to be `False` — this project never requests or
  stores hidden reasoning.
- `context_window_tokens` (`num_ctx`) and `max_output_tokens`
  (`num_predict`) are always sent explicitly; the client never depends on
  Ollama's hardware-dependent default context length.
- `temperature` defaults to `0.0`; `seed` defaults to `42` — both sent in
  `options` on every call for deterministic generation where the underlying
  model/runtime supports it.
- `max_retries` (default `1`) retries only `httpx.TransportError` (DNS/
  connection-refused/reset) on GET calls and on `POST /api/chat` itself.
  A timeout, a non-2xx status, or a malformed JSON body is never retried —
  those are surfaced as typed errors for the caller to handle.

## Digest validation

`GET /api/tags` returns each installed model's `digest`. This client does
not itself enforce `expected_digest`/`strict_digest` — that comparison is
made once, at startup, by `pipelines/answering_pipeline.py`
(`engrag-ask validate`), since a config object should not raise on
construction. Model tags can be moved/updated upstream; the observed digest
is what is actually recorded and checked, never assumed from the tag alone.

## No import-time network calls

Constructing `OllamaHTTPClient` only configures an `httpx.Client` — no
request is made until `health_check`/`version`/`list_models`/`model_info`/
`generate_structured` is actually called.

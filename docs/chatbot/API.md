# Chatbot API Reference

Base URL: `http://127.0.0.1:8000/api/v1` (host/port configurable — see
`docs/chatbot/COMMANDS.md`). Binds to loopback only by default. All
request/response bodies are JSON except upload, which is
`multipart/form-data`.

All schemas are Pydantic models defined in `src/engineering_rag/chatbot/schemas.py`;
this document describes the contract, not a generated spec — the live
OpenAPI schema is also available at `/docs` and `/openapi.json` while the
server is running (FastAPI's default).

## Error envelope

Every error response (never a raw traceback or filesystem path) has this
shape:

```json
{
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "Document not found.",
    "retryable": false,
    "correlation_id": "bb5bdd185e6d426380819ba9ba929374"
  }
}
```

`code` is a stable, machine-readable string from `chatbot/errors.py::ErrorCode`
(e.g. `DOCUMENT_NOT_FOUND`, `UPLOAD_REJECTED`, `EMPTY_DOCUMENT_SELECTION`,
`UNKNOWN_DOCUMENT_SELECTED`, `DOCUMENT_NOT_READY`, `INVALID_RETRIEVAL_MODE`,
`PARSER_VALIDATION_FAILED`, `CHUNK_VALIDATION_FAILED`, `VECTOR_INDEXING_FAILED`,
`INDEX_VALIDATION_FAILED`, `INGESTION_CANCELLED`, `INTERNAL_ERROR`). Library
exceptions are translated by `translate_exception()`, which walks the
exception's MRO by class name (never `repr(exc)`), so an unrecognised
failure always becomes a generic `INTERNAL_ERROR` rather than leaking
internal detail.

## System

| Method & path | Purpose |
|---|---|
| `GET /health` | Liveness only — `{"status": "ok", "version": "1.0.0"}` |
| `GET /ready` | Readiness (registry reachable, worker running) |
| `GET /capabilities` | Parser profiles, retrieval modes, accepted upload types/limits, provider/model info — the frontend must read limits from here, never hard-code them |
| `GET /system/status` | Dependency health (Chroma, BM25, Ollama), worker state, corpus counts — abbreviated paths only, no absolute filesystem paths, no secrets |

`GET /capabilities` example:

```json
{
  "version": "1.0.0",
  "parser_profiles": [{"id": "default", "label": "Default", "description": "..."}, ...],
  "retrieval_modes": ["vector", "hybrid", "vector-rerank", "hybrid-rerank"],
  "default_retrieval_mode": "vector",
  "accepted_extensions": [".pdf"],
  "accepted_media_types": ["application/pdf"],
  "max_upload_bytes": 104857600,
  "max_pages": 2000,
  "provider": "ollama",
  "model_tag": "qwen3:4b",
  "model_digest": "359d7dd4...",
  "generation_is_cpu_bound": true
}
```

## Documents

| Method & path | Purpose |
|---|---|
| `POST /documents` | Upload (`multipart/form-data`: `file`, optional `parser_profile`) |
| `GET /documents` | List (`?status=READY` optional filter) |
| `GET /documents/{document_id}` | Detail: status, warnings, validation summary, run ids, job history |
| `GET /documents/{document_id}/preview` | Extracted Markdown (`?max_characters=`, default 60,000) — **untrusted text; the frontend sanitises it, never renders raw HTML** |
| `POST /documents/{document_id}/reprocess` | Re-run ingestion (optionally with a new `parser_profile`); bumps the document's version and submits a `REPROCESS` job |
| `DELETE /documents/{document_id}` | Soft-delete: marks the document `DELETED`, removes its chunks from Chroma and rebuilds BM25 |

Upload response (`201 Created`):

```json
{
  "document": { "document_id": "...", "status": "UPLOADED", "sha256": "...", ... },
  "job": { "job_id": "...", "state": "QUEUED", "stage": "QUEUED", ... },
  "duplicate_of": null
}
```

**Duplicate policy** (`chatbot/uploads.py`, enforced before staging):

| Situation | Behavior |
|---|---|
| Same SHA-256, existing document `READY` | `duplicate_of` is set to the existing `document_id`; no new job is created |
| Same SHA-256, a job is already in flight | The active job is returned; no duplicate work is queued |
| Same filename, different SHA-256 | A new, distinct document — filenames never collide on disk (staged under a hashed/UUID-based storage name) |

## Jobs

| Method & path | Purpose |
|---|---|
| `GET /jobs/{job_id}` | Current job state/stage/progress/timings |
| `GET /jobs/{job_id}/events` | **Server-Sent Events** stream of stage transitions; replays a snapshot immediately if the job has already finished |
| `POST /jobs/{job_id}/retry` | Re-queue a `FAILED`/`CANCELLED`/`INTERRUPTED` job (rejected otherwise) |
| `POST /jobs/{job_id}/cancel` | Request cancellation at the next safe boundary (checked between pipeline stages, not mid-stage) |

## Conversations

| Method & path | Purpose |
|---|---|
| `POST /conversations` | Create (empty body) |
| `GET /conversations` | List |
| `GET /conversations/{id}` | Detail with full message history |
| `PATCH /conversations/{id}` | Rename |
| `DELETE /conversations/{id}` | Delete |
| `POST /conversations/{id}/messages` | Ask a question (see below) |

`POST /conversations/{id}/messages` request:

```json
{
  "query": "How often should the mechanical seal be inspected?",
  "selected_document_ids": ["<registry document_id>", "..."],
  "retrieval_mode": "vector"
}
```

`retrieval_mode` is one of `vector`, `hybrid`, `vector-rerank`,
`hybrid-rerank` (default `vector`, matching the production answering
profile). Response is `[user_message, assistant_message]`. The assistant
message:

```json
{
  "message_id": "...",
  "role": "assistant",
  "content": "The mechanical seal should be inspected every 2000 operating hours [S1].",
  "status": "answered",
  "citations": [{
    "citation_id": "S1",
    "chunk_id": "chunk_...",
    "document_id": "<source SHA-256>",
    "source_filename": "...",
    "page_numbers": [1],
    "section_title": "2. Maintenance Schedule",
    "content_hash": "...",
    "source_available": true
  }],
  "grounding": {
    "status": "PASS",
    "checks_passed": ["no_unknown_citations", "supporting_quotes_verified", ...],
    "checks_failed": [],
    "citation_coverage_ratio": 1.0,
    "repair_attempted": false
  },
  "model_tag": "qwen3:4b",
  "provider": "ollama"
}
```

`status` is one of `answered`, `insufficient_evidence`, `validation_failed`,
`failed`. Only `answered` carries trusted prose with citations; every other
status carries its own explanatory text and an empty citation list — an
unvalidated model draft is never shown as if it were a completed answer.

### Selected-document isolation (hard requirement, enforced server-side)

`selected_document_ids` is validated by `resolve_selection()` before any
retrieval happens:

- **Empty selection** → `400 EMPTY_DOCUMENT_SELECTION`. Never silently
  widened to "search everything."
- **Unknown or deleted document id** → `404 UNKNOWN_DOCUMENT_SELECTED`.
- **Not-`READY` document id** (still processing, failed, etc.) → `409 DOCUMENT_NOT_READY`.
- **Mixed valid + invalid ids** → the whole request fails (`404`); the
  valid subset is never silently answered from, because that would hide a
  wrong mental model of what was actually searched.

Only after every id passes validation are the registry ids translated to
their source SHA-256s and sent to Chroma/BM25 as a native `$in` filter
applied **before** retrieval, not a post-hoc slice of a global search — see
`docs/chatbot/SECURITY.md` for the adversarial tests that prove this.

### Citation availability after deletion

A citation is never rewritten once persisted. `source_available` is
recomputed on every read by checking whether the citation's document
SHA-256 still belongs to a non-deleted document in the registry — so
history stays honest (the exact answer and quote a user saw are preserved)
while the UI can still flag that the source is gone.

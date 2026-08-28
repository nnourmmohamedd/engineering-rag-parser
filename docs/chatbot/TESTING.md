# Testing

## Backend

| Suite | Path | Count | What it proves |
|---|---|---|---|
| State machine | `tests/unit/chatbot/test_states.py` | 25 | Every allowed/forbidden job-state transition; `is_retrievable`/`is_retryable_state` |
| Registry | `tests/unit/chatbot/test_storage.py` | 27 | CRUD, schema-version guard, restart recovery (a crash mid-embedding never promotes to `READY`) |
| Uploads | `tests/unit/chatbot/test_uploads.py` | 40 | Streamed validation order, 5 distinct path-traversal payloads, content-type spoofing, duplicate policy |
| Ingestion orchestration | `tests/integration/chatbot/test_ingestion_orchestration.py` | 24 | Every stage's gate/failure path, rollback on BM25 failure and on reconciliation mismatch (scoped to only the failing document), cancellation, idempotent retry |
| HTTP API | `tests/integration/chatbot/test_api.py` | 44 | Every endpoint, error envelopes, SSE snapshot replay, **selected-document isolation through the real HTTP layer** (empty/unknown/not-ready/mixed selections, all four retrieval modes), citation availability across deletion |
| Retriever `$in` filter | `tests/unit/services/retriever/test_filters.py` (added cases) | 7 | List → `$in`, tuple, single-element collapse, dedup, empty-list rejection |
| Document isolation (retriever layer) | `tests/unit/services/retriever/test_document_isolation.py` | 11 | Adversarial proof: unselected-document text never leaks via Chroma or BM25; filtering happens **before** top-k truncation |
| Architecture boundary | `tests/unit/test_architecture.py` (added cases) | 2 | Lower tiers never import `chatbot`; `chatbot` calls pipelines, not service internals |

**Total chatbot-specific: 160 tests** (92 unit + 68 integration), all part
of the fast suite (`pytest -m "not slow"`) — none require a real model,
real Ollama, or the real corpus. Every heavy collaborator (parser,
chunker, indexer, BM25 builder, Chroma collection, LLM client) is
injectable and faked.

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\chatbot tests\integration\chatbot -q
```

### A real bug the test suite itself had, and how it's prevented now

`tests/integration/chatbot/test_api.py`'s shared `env` fixture originally
built its `create_app()` call without injecting an orchestrator. Any test
exercising `DELETE /documents/{id}` therefore used `create_app`'s **real**
default orchestrator against the **real** production Chroma collection and
BM25 index — running the suite corrupted the real index during this
session's development (see `docs/chatbot/COMPLETION_REPORT.md` for the
full account and how it was repaired). The fixture now injects an isolated
in-memory fake Chroma collection and a no-op BM25 builder
(`_FakeCollection` in `test_api.py`), so this class of defect cannot
recur silently — but it is a concrete reminder that "the test passed"
is not the same guarantee as "the test never touched real data," and
that guarantee has to be checked, not assumed.

## Backend — real/slow suite

`tests/integration/pipelines/test_real_answering.py` (pre-existing, part
of the shared answering pipeline, reused unchanged by the chatbot) — 30
tests against a real Ollama server and the real production corpus, across
all four retrieval modes plus a real out-of-domain refusal. Marked `slow`;
excluded from the default `pytest` run.

```powershell
.venv\Scripts\python.exe -m pytest -m slow -q
```

## Real acceptance testing (this milestone, manual and one-off)

Documented in full in `docs/chatbot/COMPLETION_REPORT.md`. In summary: a
synthetic, non-confidential test PDF
(`scripts/generate_acceptance_test_pdf.py`) was uploaded through the real
HTTP API against the real production backend, real qwen3:4b model, and
real 122-chunk corpus. It reached `READY` through all 11 real pipeline
stages with a passing cross-index reconciliation; real questions were
asked and verified in all four retrieval modes; the refusal path and
post-deletion citation-availability flip were verified; the test document
was deleted through the supported lifecycle; the corpus was confirmed to
return to its **exact original 122-chunk fingerprint** (a SHA-256 of the
sorted chunk-id set, compared before and after).

This is not an automated CI gate — it requires a running Ollama server and
mutates the real corpus during the run — but it is the evidence that the
plumbing genuinely works end-to-end, not just against fakes.

## Frontend

**Unit/component (Vitest + Testing Library): 69 tests, 10 files.** Covers
the API client, formatting utilities, citation rendering, message XSS
sanitization (`<img onerror>`, `<script>` payloads are neutralized —
`react-markdown` + `rehype-sanitize`, raw HTML disabled), document
selector (including the `useId()`-namespaced desktop/mobile dual mount),
upload dropzone validation, document row actions, status badges, SSE
event hook (a custom `MockEventSource`), and the documents page's
filter/search/empty states.

```powershell
cd apps\rag-chatbot
npm test
```

**End-to-end (Playwright): 15 tests × 2 projects (chromium desktop,
mobile — Pixel 7 with real touch emulation) = 30 browser runs, all
passing.** Runs against a controlled test backend
(`e2e/fixtures/test_backend.py`) that uses the **real** orchestrator,
worker, and state machine — only Docling conversion, BGE embedding, the
reranker, and Ollama generation are faked (deterministic canned
responses), so the E2E suite genuinely exercises this application's own
logic, not a fully mocked stand-in.

Covers: document lifecycle (upload → real, observable stage transitions →
`READY`; detail view chunk counts/timings; sanitized Markdown preview;
delete confirmation dialog and cancellation; confirmed deletion); grounded
chat with citations (answer + citation panel with page/section/quote;
refusal with no fabricated sources; send disabled until a document is
selected); selected-document isolation (proven via a real intercepted
network request — the exact set of checked document ids is what's sent,
and an empty selection fires no request at all); responsive/mobile layout
(navigation drawer, table containment, the document-selection drawer, all
four retrieval modes reachable on a 390px viewport).

```powershell
cd apps\rag-chatbot
npm run test:e2e:install   # once
npm run test:e2e
```

### Real defects the E2E suite found in application code

Documented in the E2E commit message and `docs/chatbot/COMPLETION_REPORT.md`
in full; in short: a mobile table-overflow fix that didn't actually reach
the page edge, duplicate checkbox DOM ids from the selector's dual
desktop/mobile mount, a toast library's off-screen accessibility element
inflating `scrollWidth` in a way that looked like a real overflow bug but
wasn't, and a documents-polling interval that could miss a fast fake
pipeline's transient "Processing" state.

## Accessibility and responsive QA

Performed by rendering the application (via the real dev server, not just
inferred from a passing build) at desktop (1280px+), tablet (768px), and
mobile (390px) widths, in both light and dark themes, across empty,
processing, completed, and failure/refusal states. Verified: keyboard
reachability of every interactive control (including the Radix
dropdown/select/dialog components, whose focus behavior for touch vs.
keyboard activation differs — see the E2E deletion-test notes above),
visible focus rings, no color-only status communication (every status
badge pairs color with an icon and text), `prefers-reduced-motion`
respected, no horizontal page overflow at 390px (verified as real
scrollability, not just `scrollWidth`, per the finding above), and safe
Markdown rendering under adversarial XSS payloads.

## What CI runs (and deliberately does not)

See `.github/workflows/ci.yml`. The `frontend` job runs lint, typecheck,
format check, unit tests, production build, and the full Playwright E2E
suite against the faked test backend — **no real Ollama call, no real
model or embedding download, no mutation of the real Chroma/BM25
collection**, matching the same no-network-beyond-install,
no-secrets-required constraint the existing Python jobs already honor.

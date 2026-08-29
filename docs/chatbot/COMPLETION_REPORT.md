# Professional Document-Ingestion RAG Chatbot — Completion Report

**Branch:** `feature/professional-rag-chatbot`
**Baseline:** master `5bda069` (PR #6, "context-grounded-answering")
**Report date:** 2026-08-27

This report documents what was built, how it was verified, and — most
importantly — the real defects real testing found and fixed, rather than
claiming completion because files exist or tests were mocked.

## 1. What this milestone delivers

A complete local application: FastAPI + SQLite backend
(`src/engineering_rag/chatbot/`) reusing the existing parser/chunker/
embedder/retriever/answerer pipelines unchanged (plus two small, surgical
extensions the pipelines needed — metadata `$in` filtering and a threaded
`metadata_filters` parameter, both additive), and a React/TypeScript
frontend (`apps/rag-chatbot/`). Upload → durable, validated, cross-index-
reconciled ingestion → document selection → grounded, cited answering
across all four retrieval modes → source viewing → full document
lifecycle (retry, cancel, reprocess, delete). See
`docs/chatbot/ARCHITECTURE.md` for the full design.

## 2. The most important finding: a real document-identity bug

Every fake used in unit/integration/E2E tests used a self-consistent id
scheme, which masked a real defect: this application's own registry
`document_id` (an internal bookkeeping UUID) was being used to query
Chroma and BM25 directly, but those databases actually key every chunk by
the **source file's own SHA-256** — a deliberate, pre-existing, content-
addressed identity from `services/chunker/ids.py`, unrelated to and
predating this application.

Discovered only once real acceptance testing ran a real document through
the real pipeline: ingestion reconciliation failed every time (empty
`chroma_chunk_ids` for the wrong id, so `ReconciliationReport.consistent`
was never true), meaning **no real document could ever reach `READY`
before this fix.** The same mismatch meant selected-document retrieval
isolation and document deletion were both silently non-functional against
real data.

Fixed at every call site (`ingestion.py::reconcile`/`rollback_document`,
`app.py::delete_document`, `answering.py`'s selected-document filter) by
translating through `registry.get_document(id).sha256` before touching
Chroma/BM25. A related gap — `services/answerer/models.py::CitationSummary`
never carried `document_id` at all, even though the underlying
`SelectedSource` already had it — was fixed with a one-field addition, so
"mark a citation unavailable after its source is deleted" could work at
all. Full account, including the exact traceback and diagnosis steps: see
the commit `51a8d7f` message.

## 3. A second real finding: a test-isolation gap that corrupted production data

While investigating the id bug, running the chatbot test suite was found
to actually mutate the real production Chroma/BM25 index: `test_api.py`'s
shared `env` fixture built its FastAPI app without injecting an
orchestrator, so `create_app()`'s real default orchestrator — pointed, by
default, at the real production paths — was used by any test exercising
`DELETE /documents/{id}`. This corrupted the real BM25 index (127 records
vs. the correct 122) during this session's own development. Fixed by
giving the fixture an isolated fake Chroma collection and a no-op BM25
builder. The real index was rebuilt from the (already-correct) real Chroma
state and verified back to an exact fingerprint match with the pre-testing
corpus (see §5). The full fast suite was re-run afterward and confirmed
**not** to touch `data/output/` at all.

## 4. Architecture, tech stack, lifecycle

- **Backend:** FastAPI + Pydantic + Uvicorn + SQLite (`sqlite3`, WAL mode,
  explicit schema-version guard) — see `docs/chatbot/ARCHITECTURE.md`.
- **Frontend:** React 18 + TypeScript strict + Vite + Tailwind + shadcn-
  style components + TanStack Query + React Router (`HashRouter`) +
  `react-markdown`/`rehype-sanitize` — entirely inside `apps/rag-chatbot/`,
  pinned dependency versions, committed lockfile.
- **Lifecycle:** upload → stage → validate (extension, size, `%PDF-`
  signature, SHA-256) → durable job → parse → validate → chunk → validate
  → embed → index → BM25 → cross-index reconcile → atomic activation →
  `READY`. Retry, cancel (at safe boundaries), reprocess, soft-delete all
  implemented and tested — see `docs/chatbot/DOCUMENT_LIFECYCLE.md`.
- **Formats:** PDF only, advertised as such via `/capabilities` (never
  hard-coded in the frontend).

## 5. Real ingestion evidence

A synthetic, non-confidential test PDF was generated
(`scripts/generate_acceptance_test_pdf.py` — fictional "SP-100 pump"
maintenance manual, four sections) and run through the **real** backend
(no fakes), the **real** `qwen3:4b` model via a real local Ollama server,
and the **real** production 122-chunk `engineering_documents_v1` corpus.

| Step | Result |
|---|---|
| Fingerprint before testing | 122 chunks, SHA-256 of sorted chunk-id set: `6a54ac99...` |
| Upload → `READY` | All 11 real pipeline stages completed in ~17.5s; `validation_summary.consistent: true`; 5 chunks |
| Delete | `chunks_removed: 5` |
| Fingerprint after testing | 122 chunks, **same** SHA-256 `6a54ac99...` — exact match |
| Cross-index check | `chroma_ids == bm25_ids`, both 122, both times |

## 6. Real selected-document isolation evidence

Beyond the adversarial unit tests (`tests/unit/services/retriever/test_document_isolation.py`,
11 tests) and the real-HTTP-layer tests
(`tests/integration/chatbot/test_api.py::TestAskSelectionIsolation`),
isolation was proven through the real Playwright E2E suite
(`e2e/selection-isolation.spec.ts`) by intercepting the real network
request and asserting `selected_document_ids` in the POST body matches
exactly the checked documents, and that an empty selection fires no
request at all.

## 7. Real answering evidence, all four modes

Asked against the real synthetic test document, real model, real corpus:

| Mode | Question | Result |
|---|---|---|
| `vector` | mechanical seal inspection interval | "...every 2000 operating hours [S1]." — grounding `PASS`, citation verified against the actual indexed chunk text |
| `hybrid` | safety precautions before maintenance | Correct, full 3-sentence answer — grounding `PASS_WITH_WARNINGS` |
| `vector-rerank` | rated flow/head | "250 cubic meters per hour... 45 meters [S1]." — grounding `PASS` |
| `hybrid-rerank` | causes of excessive vibration | "impeller imbalance, cavitation..., or worn bearings [S1]." — grounding `PASS` |
| refusal (`vector`) | out-of-domain ("capital of France") | `status: insufficient_evidence`, zero citations — see the noted model-prose limitation in `docs/chatbot/SECURITY.md` |

Every citation was independently verified by reading the corresponding
chunk directly out of Chroma and confirming the cited text is actually
present. Citation `source_available` was confirmed to flip from `true` to
`false` immediately after the cited document was deleted (for citations
created after the `CitationSummary.document_id` fix — see the noted
sha256-aliasing limitation for pre-fix citations, documented honestly in
`docs/chatbot/SECURITY.md`).

Additionally, the shared answering pipeline's own real/slow suite
(`tests/integration/pipelines/test_real_answering.py`, reused unchanged)
passed 30/30 against real Ollama across all four modes plus a real
out-of-domain refusal.

## 8. UI pages

Chat (document selector, retrieval-mode selector, live progress, citation
panel, refusal/error states, mobile drawer), Documents (drag-drop upload,
parser-profile selector, real progress, filters/search/sort, retry/cancel/
reprocess/delete), Document Detail (metadata, timeline, stage timings,
validation, warnings, Markdown preview, job history), System (dependency
health, worker status, theme toggle).

## 9. Security and failure-handling evidence

See `docs/chatbot/SECURITY.md` for the full account: streamed upload
validation with 5 distinct path-traversal payloads tested, content-type
spoofing rejection, loopback-only binding with an explicit non-wildcard
CORS allow-list, a typed error envelope that never leaks a traceback or
filesystem path (`translate_exception`), scoped (never collection-wide)
Chroma rollback/delete, and the two limitations disclosed above.

## 10. Test counts

| Suite | Count |
|---|---|
| Chatbot backend unit | 92 |
| Chatbot backend integration | 68 |
| Retriever document-isolation (adversarial) | 11 |
| Architecture-boundary (chatbot-specific additions) | 2 |
| **Chatbot backend total** | **173** |
| Full repository fast suite (`pytest -m "not slow"`) | **1014 passed**, 88 deselected |
| Frontend unit/component (Vitest) | 69 |
| Frontend E2E (Playwright, chromium + mobile projects) | 15 × 2 = 30 browser runs, all passing |

## 11. Quality gates

| Gate | Result |
|---|---|
| `ruff format --check .` | Clean (350 files) |
| `ruff check .` | Clean, all rules including `ARG` |
| `mypy src` | Clean, 149 source files |
| `pytest -m "not slow"` + coverage | **1014 passed**, coverage **85.59%** (gate: 55%) |
| Notebook validation | All 5 notebooks structurally valid |
| Wheel build | Succeeds; contains no PDF/confidential content; contains the full chatbot package |
| Clean-install smoke test | Wheel installs into an isolated venv; `import engineering_rag` and CLI entry points resolve |
| Frontend `typecheck` | Clean |
| Frontend `lint` (`--max-warnings 0`) | Clean |
| Frontend `format:check` | Clean |
| Frontend `npm test` | 69/69 |
| Frontend `npm run build` | Succeeds |
| `npm audit` | 2 moderate advisories, both assessed non-applicable (no SSR, no user-controlled navigation); reduced from 11 (1 critical, 7 high) via manual pinning rather than `--force` |

## 12. Accessibility and responsive QA

Performed by rendering the real dev server at desktop/tablet/mobile
widths, light/dark themes, empty/processing/completed/failure states — see
`docs/chatbot/TESTING.md` for the specific checks (keyboard reachability,
focus rings, no color-only status, `prefers-reduced-motion`, verified real
horizontal scrollability at 390px rather than an unreliable `scrollWidth`
check, safe Markdown/XSS handling).

## 13. CI

`.github/workflows/ci.yml` gained a `frontend` job (Node 20, `ubuntu-latest`)
alongside the existing, unmodified Python 3.11/3.13 jobs: typecheck, lint,
format check, unit tests, production build, and the full Playwright E2E
suite (chromium project) against the faked test backend. No real Ollama
call, no model download beyond CPU-only PyTorch (already required by the
Python jobs), no mutation of real Chroma/BM25, no secrets required.

## 14. Limitations, stated honestly

- Single-user, local, no authentication — see `docs/chatbot/SECURITY.md`.
- Citation source-availability can alias across duplicate uploads of
  identical content (documented, narrow edge case; see `SECURITY.md`).
- The refusal path's exact prose is model-dependent; the `status` field
  and absence of fabricated citations are always correct.
- Human semantic review of answer *quality* (as opposed to this
  application's plumbing, which was verified end-to-end against real
  data) has not been performed beyond the acceptance queries in §7 — the
  underlying answering pipeline's evaluation corpus remains
  `machine_candidate` per the prior milestone's own disclosure.
- OpenAI provider is not implemented — the `AnswerProvider` Protocol is
  shaped to allow one without touching retrieval/grounding/UI, but only
  Ollama is wired up, and no OpenAI testing was performed or fabricated.

## 15. Branch / PR status

Branch `feature/professional-rag-chatbot`, pushed to origin. **Pull
request opened against `master`, not merged** — see the PR description for
the exact compare link if `gh` was unavailable at delivery time.

## 16. Post-merge defect (2026-08-29): re-ingesting already-indexed content

The first real document upload after this milestone merged into `master`
failed three times in a row: `INTERNAL_ERROR` on the first attempt,
`VECTOR_INDEXING_FAILED` on the next two, all at the `VECTOR_INDEXING`
stage. Diagnosis, fix and verification are on branch
`fix/chatbot-reingest-content-hash-idempotency`; full detail is now in
`docs/chatbot/TROUBLESHOOTING.md` under "A document failed with
`VECTOR_INDEXING_FAILED` mentioning a content conflict". Summary:

**Root cause.** `content_hash()` — the fast-path check deciding
"identical content, skip" vs. "different content, refuse to
overwrite" in `databases/chroma/repository.py::ingest_batch` — hashed
two fields that are run/upload *provenance*, not chunk *content*:
`chunk_run_id` (a fresh timestamp every chunker run) and
`source_filename` (whatever the file was staged/parsed as on disk this
time — a generated storage name for a chatbot upload, never the
original filename a document might already be indexed under from a
prior CLI run). Any re-ingestion of already-indexed, byte-identical
content therefore always looked like a hard conflict, and
`DuplicateIdConflictError` had no entry in the API's error-translation
table, so it surfaced as an opaque `INTERNAL_ERROR`.

**Compatibility behavior.** Correcting the hash formula alone cannot
repair a corpus indexed before the fix, because its stored hashes were
computed under the old formula and can never again equal a hash from
the corrected one — for any document, indefinitely. `ingest_batch` now
falls back to comparing the actual stored retrieval text when the
fast-path hash disagrees, before declaring a real conflict. This makes
the fix retroactively correct against a pre-existing, unmodified corpus
with no migration, re-embedding, or rebuild of any kind. A batch with a
genuinely different chunk under the same id still raises
`DuplicateIdConflictError` and still writes nothing for that batch —
this path is unchanged and covered by
`test_conflicting_duplicate_id_rejected` and (new)
`test_mixed_batch_stays_atomic_on_one_real_conflict`.

**Evidence.** The failing document's own SHA-256 matched an
already-indexed acceptance PDF (added directly via the CLI pipeline,
outside the chatbot's registry). All 113 of its chunks were confirmed
byte-identical, field-by-field, to the 113 already in the corpus. After
the fix, the same registered document (`b36b90175bb04ec79e4d4a37f558195c`
— no re-upload) reached `READY` on retry with 113/113 chunks resolving
as idempotent-identical: the shared corpus grew by **zero** records
(122 before, 122 after, in both Chroma and BM25), and
`GET /api/v1/documents/{id}` reported
`{"chroma_chunk_count": 113, "bm25_chunk_count": 113, "consistent": true}`.
All four job attempts (three failures, one success) remain in the jobs
table as preserved evidence. Selected-document retrieval isolation was
verified bidirectionally with `engrag-retrieve search --filter
document_id=...` against another, unrelated document already in the
corpus: a query semantically matching only the other document, scoped
to this one, returned zero hits from the other document, and vice
versa; an in-domain query scoped to this document returned correct,
relevant sections.

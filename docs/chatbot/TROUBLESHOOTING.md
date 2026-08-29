# Troubleshooting

## Backend won't start

- **`ModuleNotFoundError: fastapi`** — install the `chatbot` extra:
  `pip install -e ".[chatbot]"`.
- **Port already in use** — set `ENGRAG_CHATBOT_PORT` to a free port, or
  stop whatever is bound to 8000.
- **`RegistrySchemaError`** — the SQLite registry at
  `data/chatbot/registry.sqlite3` was created by an incompatible schema
  version. Back it up and remove it (`Remove-Item data\chatbot\registry.sqlite3`)
  to let it be recreated; you'll lose local conversation history and
  document metadata, but not the shared Chroma/BM25 corpus.

## `GET /api/v1/system/status` shows a dependency as unhealthy

- **Ollama unreachable** — confirm `ollama list` shows `qwen3:4b` and the
  server is actually running (`ollama serve`, or check it's already
  running as a background service). The default endpoint is
  `http://localhost:11434`.
- **Chroma/BM25 path missing or empty** — confirm
  `configs/retrieval_production.yaml`'s paths exist and the corpus has
  actually been built (see the parser/chunker/indexing docs under
  `docs/` for how the base corpus is produced — that's a separate,
  already-completed milestone this chatbot consumes, not something it
  builds itself).

## A document is stuck in `PROCESSING`

Check its job detail (`GET /api/v1/jobs/{id}`) or the detail page in the
UI — `stage_timings` shows exactly which stage is running and how long
each prior stage took. Parsing and embedding are the slowest stages for
large/complex PDFs; give it time before assuming it's hung. If the backend
process itself crashed or was restarted, the job becomes `INTERRUPTED` on
the next startup (never silently `READY`) — retry it explicitly.

## A document failed with `CHUNK_VALIDATION_FAILED` mentioning a tokenizer mismatch

This means the chunker's configured tokenizer doesn't match the embedding
model's. The chatbot's default chunker profile
(`ChatbotConfig.chunker_profile`, `configs/chunker_bge.yaml`) is already
aligned with the production embedding model (`BAAI/bge-base-en-v1.5`); if
you've changed `ENGRAG_CHATBOT_RETRIEVAL_PROFILE` to a different embedding
model, you likely need a matching chunker profile too — see
`configs/chunker_bge.yaml`'s header comment for the reasoning, and
`docs/chunker/CONFIGURATION.md` for what each parameter controls.

## A document failed with `INDEX_VALIDATION_FAILED`

Chroma and BM25 disagreed about this document's chunk set after
processing — the document was **not** activated, and both indexes were
rolled back to their pre-ingestion state (Chroma records for this document
removed; BM25 restored from its pre-mutation snapshot). This is designed
to fail safely rather than leave an inconsistent corpus. Retry the job; if
it fails again consistently, check `GET /api/v1/system/status` for a
pre-existing cross-index inconsistency unrelated to this specific upload
(rebuild BM25 from Chroma to fix — see `docs/chatbot/COMMANDS.md`'s
"Reset local state" section).

## A document failed with `VECTOR_INDEXING_FAILED` mentioning a content conflict

This means the document's content is already present in the shared
Chroma/BM25 corpus (e.g. it was previously indexed via the CLI pipeline
directly, outside the chatbot's own registry) and the fast-path
`content_hash` comparison couldn't confirm that on its own — usually
because the stored hash predates a hash-formula change, or because you're
running a build that still has the underlying bug this section describes.
`GET /api/v1/system/status` shows the shared corpus's dependency health;
retry the job (`POST /api/v1/jobs/{id}/retry`) once you've confirmed the
backend is on a fixed build — a genuine re-ingestion of unchanged content
resolves as an idempotent no-op, not an error.

**Root cause (fixed 2026-08-29).** `content_hash()` — the check that
decides "same content, skip" vs. "different content, refuse to
overwrite" — used to hash two fields that are upload/run *provenance*,
not chunk *content*:

- `chunk_run_id`, a fresh timestamp generated on every chunker run, even
  when the actual chunk text never changed;
- `source_filename`, the name the file happened to be staged/parsed
  under this run — for a chatbot upload this is a generated storage
  filename, never the original name a document might have been indexed
  under previously (e.g. via the CLI pipeline).

Because of this, re-ingesting a document whose content was already
indexed (by any path) always produced a different hash from what was
stored, even for byte-identical text — permanently defeating the
idempotent-skip path and raising `DuplicateIdConflictError`, which had
no entry in the API's error-translation table and so surfaced as an
opaque `INTERNAL_ERROR` with no actionable detail.

Fixing the hash formula alone could not repair documents already in an
existing corpus, because their stored hashes were computed under the old
formula and could never again equal a hash computed by the corrected
one. The complete fix has three parts:

1. `chunk_run_id` and `source_filename` are still recorded in each
   chunk's stored metadata (for provenance and citation display) but are
   now excluded from what `content_hash()` hashes.
2. `DuplicateIdConflictError` has a proper `VECTOR_INDEXING_FAILED`
   translation instead of falling through to `INTERNAL_ERROR`.
3. `ingest_batch` now falls back to comparing the actual stored
   retrieval text when the fast-path hash disagrees, before declaring a
   real conflict — this is what makes already-indexed, pre-fix corpora
   (including ones built before this fix existed) resolve correctly
   without any migration or rebuild.

A batch with one genuine conflict (different id, truly different text)
still raises and still writes nothing for that batch — atomicity is
unchanged; see `tests/integration/databases/chroma/test_repository_integration.py::TestCollectionLifecycle::test_mixed_batch_stays_atomic_on_one_real_conflict`.

**Evidence.** Diagnosed against a real production incident: a document
whose SHA-256 matched an already-indexed acceptance PDF failed
ingestion three times with `INTERNAL_ERROR`/`VECTOR_INDEXING_FAILED`
before the fix. After the fix, the same registered document (no
re-upload) reached `READY` on retry with 113/113 chunks resolving as
idempotent-identical to the existing corpus — the shared 122-chunk
Chroma/BM25 corpus grew by exactly zero records, and cross-index
consistency (`chroma_chunk_count`/`bm25_chunk_count`/`missing_from_*`)
stayed reported as `consistent: true`. Selected-document retrieval
isolation was verified bidirectionally against another document already
in the corpus: a query semantically matching only the other document,
scoped to this one, returned zero results from the other document, and
vice versa.

## Upload is rejected

- **"Unsupported file type"** — only `.pdf` is accepted; check the actual
  file extension and content, not just what you renamed it to.
- **"File too large" / "Too many pages"** — check
  `GET /api/v1/capabilities` for the currently configured limits
  (`ENGRAG_CHATBOT_MAX_UPLOAD_BYTES` to change the size limit).
- **"Invalid PDF"** — the file's first bytes don't match the `%PDF-`
  signature; it isn't actually a PDF, or it's corrupted.

## Asking a question does nothing / the send button is disabled

Select at least one `Ready` document first — the question box is
disabled and an explanatory message is shown until you do. An empty
selection is never silently treated as "search everything."

## An answer takes a long time / seems to hang

Generation via `qwen3:4b` through local Ollama is **CPU-bound** and can
take from tens of seconds to a few minutes depending on your hardware —
this is expected, not a bug. The UI shows live stage progress (retrieval →
generation → grounding) rather than a static spinner; if that progress
genuinely stops advancing for several minutes, check the backend log for
an Ollama connection error.

## An answer was refused ("insufficient evidence")

This means grounding validation could not find enough supporting evidence
in your *selected* documents for the question — it is the system working
as designed (never presenting an unsupported answer as fact), not an
error. Try selecting more documents, rephrasing the question to more
closely match the document's own terminology, or trying a different
retrieval mode (Hybrid can help for exact-phrase questions).

## A citation shows "source unavailable"

The document that citation came from has since been deleted. The exact
quote, page and section you were originally shown is preserved — only its
current availability is flagged. This is by design (see
`docs/chatbot/DOCUMENT_LIFECYCLE.md`).

## E2E tests fail locally on Windows

Confirm `apps/rag-chatbot/e2e/fixtures/paths.ts`/`playwright.config.ts`
can resolve the repo's own `.venv\Scripts\python.exe` (the default
resolution on Windows) — if you're running from a different venv location,
set `PLAYWRIGHT_PYTHON_BIN` to the correct interpreter path explicitly.

## Frontend build fails with a TypeScript error after pulling changes

```powershell
cd apps\rag-chatbot
Remove-Item -Recurse -Force node_modules, package-lock.json -ErrorAction SilentlyContinue
npm install
npm run typecheck
```

Only do this if `npm ci` with the committed lockfile doesn't already
resolve it — regenerating the lockfile should be a last resort, since it
can pull newer transitive versions than were tested.

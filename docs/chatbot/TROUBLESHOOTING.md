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

# Commands (PowerShell)

All commands assume the repository root as the working directory unless
noted. `.venv` is the repo's existing Python virtual environment.

## First-time setup

```powershell
# Python backend: install the chatbot extra (fastapi/uvicorn/python-multipart)
# plus whatever pipeline extras you need for real ingestion/answering.
.venv\Scripts\python.exe -m pip install -e ".[dev,chatbot,chunking,indexing,hybrid,answering]"

# Frontend
cd apps\rag-chatbot
npm ci
cd ..\..
```

```powershell
# Ollama must be running locally with the production model pulled.
ollama pull qwen3:4b
ollama list   # confirm qwen3:4b is present
```

## Run the backend

```powershell
.venv\Scripts\python.exe -m uvicorn engineering_rag.chatbot.app:create_app --factory --host 127.0.0.1 --port 8000
```

`create_app()` works with zero arguments against real production data
(`configs/answering_production.yaml`, `configs/retrieval_production.yaml`,
`data/output/databases/chroma`, `data/output/databases/bm25`) — every
collaborator is optionally injectable for tests, but the defaults are the
real pipeline.

## Run the frontend (dev)

```powershell
cd apps\rag-chatbot
npm run dev
```

Vite proxies `/api` to the backend (default `http://127.0.0.1:8000`; see
`vite.config.ts` to change the proxy target). Open the printed local URL
(default `http://localhost:5173`).

## Configuration (environment variables)

All optional; every default is safe for local single-user use.

| Variable | Default | Purpose |
|---|---|---|
| `ENGRAG_CHATBOT_DATA_ROOT` | `data/chatbot` | Registry DB, uploads, staging, backups |
| `ENGRAG_CHATBOT_MAX_UPLOAD_BYTES` | `104857600` (100 MiB) | Upload size limit |
| `ENGRAG_CHATBOT_HOST` | `127.0.0.1` | Server bind address — **do not change without adding auth+HTTPS first**, see `SECURITY.md` |
| `ENGRAG_CHATBOT_PORT` | `8000` | Server port |
| `ENGRAG_CHATBOT_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated allow-list; never set to `*` |
| `ENGRAG_CHATBOT_WORKER_CONCURRENCY` | `1` | Ingestion worker thread-pool size |
| `ENGRAG_CHATBOT_ANSWERING_PROFILE` | `configs/answering_production.yaml` | Answering pipeline profile path |
| `ENGRAG_CHATBOT_RETRIEVAL_PROFILE` | `configs/retrieval_production.yaml` | Retrieval pipeline profile path |

A non-secret template is at `apps/rag-chatbot/.env.example` (frontend build-time
variables only — the backend reads the `ENGRAG_CHATBOT_*` variables above
directly from the process environment, not from a `.env` file).

## Tests

```powershell
# Backend: fast tests (excludes the real-Ollama/real-corpus slow suite)
.venv\Scripts\python.exe -m pytest -m "not slow" --cov=engineering_rag --cov-report=term-missing

# Backend: chatbot-specific suites only
.venv\Scripts\python.exe -m pytest tests\unit\chatbot tests\integration\chatbot -q

# Backend: slow/real suite (needs a running Ollama with qwen3:4b, and the
# real acceptance PDF if that specific test is included — most chatbot
# slow tests do not need it)
.venv\Scripts\python.exe -m pytest -m slow -q

# Frontend: typecheck, lint, format, unit tests, build
cd apps\rag-chatbot
npm run typecheck
npm run lint
npm run format:check
npm test
npm run build

# Frontend: end-to-end (installs Chromium once)
npm run test:e2e:install
npm run test:e2e
```

## Build

```powershell
# Python wheel
.venv\Scripts\python.exe -m build --wheel

# Frontend production bundle
cd apps\rag-chatbot
npm run build   # outputs to apps\rag-chatbot\dist
```

## Reset local state

```powershell
# Wipe the chatbot's own registry/uploads/staging (documents, jobs,
# conversations) -- does NOT touch the shared Chroma/BM25 corpus.
Remove-Item -Recurse -Force data\chatbot

# Rebuild BM25 from the current Chroma state (idempotent; --force to rebuild
# even if unchanged). Only needed if the two indexes are ever found
# inconsistent -- GET /api/v1/system/status reports this.
.venv\Scripts\engrag-retrieve.exe build-bm25 --profile configs\retrieval_production.yaml --force
```

There is no destructive command that touches the shared parser/chunker
corpus (`data/output/databases/`) as part of normal chatbot operation —
only an explicit document delete (scoped to that document) or the BM25
rebuild above (a read of Chroma, a full rewrite of the BM25 index only)
ever mutate it.

## Logs

The backend logs to stdout/stderr (structured via
`engineering_rag.utils.logging`); redirect as needed:

```powershell
.venv\Scripts\python.exe -m uvicorn engineering_rag.chatbot.app:create_app --factory > chatbot.log 2>&1
```

Ingestion failures are logged with the document/job id and translated
error code, never a full traceback client-side (see `SECURITY.md`).

## Version / help checks

```powershell
.venv\Scripts\python.exe -c "import engineering_rag; print(engineering_rag.__version__)"
.venv\Scripts\engrag-parse.exe --help
.venv\Scripts\engrag-chunk.exe --help
.venv\Scripts\engrag-index.exe --help
.venv\Scripts\engrag-retrieve.exe --help
.venv\Scripts\engrag-ask.exe --help
```

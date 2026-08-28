# Security

## Scope and threat model

This is **local, single-user software with no authentication.** It is
designed to be run on `127.0.0.1` by one person on their own machine. It
is **not** designed to be exposed to a network, a multi-user environment,
or the public internet as-is.

`ServerConfig.host` defaults to `127.0.0.1`
(`ServerConfig.binds_to_loopback_only` is `True` for `127.0.0.1`,
`localhost`, `::1`). CORS (`ServerConfig.cors_origins`) defaults to the
exact local Vite dev origins (`http://localhost:5173`,
`http://127.0.0.1:5173`) — **never `*`**, so no arbitrary web page can call
this API from a browser even if a user has it running.

**Before exposing this application beyond loopback**, you must add
authentication and put it behind HTTPS (a reverse proxy with TLS
termination and, at minimum, HTTP basic auth or a real session/auth layer
is the practical minimum). This milestone does not add either, because the
brief scopes this as local single-user software — treat any other
deployment as unsupported until that work is done.

## Upload handling

- **Extension allow-list**: `.pdf` only (`uploads.py::ACCEPTED_EXTENSIONS`).
- **Streamed validation**: the file is validated *while* it is being
  written to a staging directory, in order — extension, declared
  content-type, size (rejected as soon as the streamed byte count exceeds
  `max_upload_bytes`, not after the whole file lands), `%PDF-` magic-byte
  signature, then SHA-256. A file that fails any check never reaches
  durable storage.
- **Filename sanitization / path-traversal**: the original filename is
  never used as a path component for the staged or stored file — both get
  a generated name. Adversarial inputs (`../../etc/passwd`,
  `..\\..\\windows\\system32\\config`, null bytes, absolute paths,
  home-directory expansion) are covered by
  `tests/unit/chatbot/test_uploads.py` (5 distinct traversal payloads).
- **Content-type spoofing**: a declared `image/png` content-type on a
  `.pdf`-named file (or vice versa) is rejected; the check is on the
  actual streamed bytes' signature, not the client-supplied MIME type
  alone.
- **Size and page limits**: `max_upload_bytes` (100 MiB default),
  `max_pages` (2000 default) — both configurable via
  `ENGRAG_CHATBOT_MAX_UPLOAD_BYTES` (see `docs/chatbot/COMMANDS.md`).
- **Quarantine on failure**: a rejected or failed upload's staged bytes are
  discarded (`discard_staged_upload`); nothing partial or invalid is ever
  promoted to durable storage.
- **No secrets in logs**: correlation ids are logged, not file contents,
  paths beyond an abbreviated form, or request bodies.

## Selected-document retrieval isolation

This is the single hardest security requirement in the milestone, and the
one most vulnerable to a subtle bug (see
`docs/chatbot/COMPLETION_REPORT.md` for the real defect real acceptance
testing found and fixed here). The guarantee:

> Retrieval is restricted to the caller's selected documents **at query
> time**, in both Chroma and BM25 — never "retrieve globally, then filter
> or hide the results."

Enforcement:

1. `resolve_selection()` validates every requested document id
   (`chatbot/answering.py`) before any retrieval call is made: empty
   selection is rejected outright, unknown/deleted ids are rejected,
   not-`READY` ids are rejected. A partially-valid selection fails the
   whole request rather than silently answering from the valid subset.
2. The validated registry ids are translated to their source SHA-256s
   (what Chroma/BM25 actually key chunks by — see
   `docs/chatbot/ARCHITECTURE.md`'s "Document identity" section) and sent
   as `metadata_filters={"document_id": [sha256, ...]}`.
3. Chroma applies this as a native `{"$in": [...]}` where-clause
   (`services/retriever/filters.py`) — the filter is part of the vector
   query itself, not a post-processing step.
4. BM25 (`services/retriever/bm25_retriever.py::_matches_filters`) applies
   the same membership test **before** truncating to `top_k`, so a
   selected document's relevant chunk cannot be pushed out of the result
   set by unselected documents that happened to rank higher in the
   unfiltered corpus.

Adversarial proof (`tests/unit/services/retriever/test_document_isolation.py`,
11 tests): unselected-document text never leaks through either index;
empty selection returns nothing rather than being silently treated as
"everything"; an unknown document id yields nothing rather than falling
back to a global search; a mixed valid/invalid selection returns only the
valid subset's *filter*, never data from the invalid one; filtering is
proven to happen before top-k truncation (the case that would most easily
mask a bug that "usually" looks correct).

## Deletion and index integrity

Deleting a document removes its chunks from Chroma and rebuilds BM25 from
the result, scoped strictly to that document's SHA-256
(`databases/chroma/repository.py::delete_document_records`) — never a
collection-wide operation. A failed or partial ingestion is rolled back the
same way. Both are proven, in `tests/integration/chatbot/test_ingestion_orchestration.py`,
to remove *only* the failing/deleted document's chunks and leave every
other document's chunks untouched.

## Error handling

Every exception that reaches the API boundary is translated
(`errors.py::translate_exception`) by walking the exception class's MRO by
**name**, never by rendering `repr(exc)` or a traceback into the response.
An unrecognised exception becomes a generic `INTERNAL_ERROR` with a
correlation id — enough to find the real error in the server log, nothing
that leaks a filesystem path, a stack frame, or an internal identifier to
the client.

## Known limitations (stated honestly)

- **No authentication.** By design for this milestone; see above.
- **Citation source-availability can alias by content.** Availability is
  computed by checking whether the citation's source SHA-256 still belongs
  to *any* non-deleted document row. If the same file was uploaded twice
  (e.g. once as a failed attempt, once successfully) and only one copy is
  deleted, a citation from the deleted copy can still show
  `source_available: true` as long as another row with identical content
  remains in any non-deleted state. This was observed during real
  acceptance testing (see `COMPLETION_REPORT.md`) and is a real, if
  narrow, edge case — the primary case (delete the only document with
  that content) is correct and covered by tests. A complete fix would
  require citations to carry the specific ingesting document's registry
  id, not just the pipeline's content-addressed SHA-256; out of scope for
  this milestone.
- **The refusal message is model-dependent.** When the LLM itself
  determines a question has insufficient evidence (rather than retrieval
  returning zero candidates), the shown message is whatever the model
  wrote in its own `answer` field — which was observed, once, to be the
  terse literal string `insufficient_evidence` rather than a full
  sentence. The `status` field is always correct (`insufficient_evidence`,
  no citations, no fabricated sources); the prose quality is a property of
  the shared, already-merged answering pipeline and prompt, not something
  this milestone's code changed.

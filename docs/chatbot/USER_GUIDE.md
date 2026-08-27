# User Guide

## What this is

A local chat interface over your own PDF documents. You upload PDFs, the
application parses, chunks, embeds and indexes them, and you ask questions
that are answered *only* from the documents you explicitly select — with
every claim backed by a citation you can open and verify against the
original text.

It runs entirely on your machine: the language model (`qwen3:4b`) runs
through a local Ollama server, and the vector/lexical indexes are local
files. Nothing is sent to a third-party API.

## Before you start

- Ollama must be running locally with `qwen3:4b` pulled (`ollama pull qwen3:4b`).
- **Generation is CPU-bound and can take from tens of seconds to a few
  minutes per answer**, depending on your hardware — there is no GPU
  requirement, but there is no shortcut either. The UI shows real,
  observable progress rather than a fake spinner; be patient on first use.

## Uploading a document

1. Go to **Documents**, drag a PDF onto the drop zone (or click to browse).
2. Only `.pdf` files are accepted, up to the configured size/page limit
   (shown on the page; default 100 MiB / 2000 pages).
3. Optionally choose a parser profile:
   - **Default** — balanced settings for ordinary digitally-generated PDFs.
   - **High fidelity** — slower, more thorough; use for complex tables/layouts.
   - **Scanned / OCR** — for image-only or scanned PDFs; noticeably slower.
   - **Automatic** — inspects the document and picks a profile itself.
4. Watch the document move through real stages (Parsing → Chunking →
   Embedding → Indexing → Ready). If it fails, the row shows why, and
   **Retry** re-runs the pipeline.
5. Uploading the exact same file twice is safe: if it's already `Ready`,
   you're pointed at the existing document instead of a duplicate; if it's
   still processing, you're pointed at that in-flight job.

## Asking a question

1. Go to **Chat**.
2. In the document panel (a side panel on desktop, a drawer on mobile —
   tap **Options**), check every document you want the answer restricted
   to. **At least one is required** — the question box stays disabled
   until you've selected something, and an empty selection is never
   silently treated as "search everything."
3. Pick a retrieval mode if you want to override the default:
   - **Vector** — semantic similarity only (the default).
   - **Hybrid** — vector plus keyword (BM25) search, fused.
   - **Vector + Rerank** — vector search, then a cross-encoder reranks the
     candidates for relevance.
   - **Hybrid + Rerank** — hybrid search, then reranking.
4. Type your question and send. Progress is shown live (retrieval →
   generation → grounding validation) — the answer only appears once it
   has passed grounding.
5. Every claim in the answer is followed by a bracketed marker like
   `[S1]`. Click it to open that citation: source filename, page number,
   section heading, chunk id, and the exact supporting quote the model
   was validated against.
6. If the selected documents don't contain enough evidence, you get an
   explicit refusal — never a fabricated or unsupported answer.

## Document detail

Click any document in the list to see: full metadata, per-stage timings,
validation warnings, cross-index consistency summary, its complete job
history (including past failures and retries), and a rendered preview of
the extracted Markdown.

## Deleting a document

From the document list or detail page, choose **Delete**. You're shown
exactly what this does (the document becomes unsearchable, its indexed
chunks are removed) before you confirm. Past conversations that cited this
document are **not altered** — the exact quote and page you were shown at
the time are preserved — but the source is now marked unavailable in the
citation view.

## Retrieval modes, plainly

If you're not sure which mode to use: **Vector** is the default and works
well for most questions. Try **Hybrid** if your question uses specific
terms, part numbers, or exact phrases the document uses verbatim — keyword
search catches things pure semantic similarity can miss. The **+ Rerank**
variants trade a little extra latency for generally more relevant
top-ranked evidence, most noticeable on longer or more ambiguous
documents.

## System page

Shows backend, Ollama, Chroma and BM25 health, worker status, and corpus
counts — useful for confirming everything is actually running before you
report an app-level problem. See `docs/chatbot/TROUBLESHOOTING.md` if
something looks wrong here.

## Limitations, stated plainly

- Single-user, local software — see `docs/chatbot/SECURITY.md` before
  considering any shared or remote deployment.
- PDF only.
- Answer generation quality is that of `qwen3:4b`; it is not infallible,
  and grounding validation catches *unsupported claims*, not *every*
  possible factual error a genuinely supported passage might itself
  contain.
- The underlying retrieval/answering quality (as opposed to this
  application's plumbing) has not undergone a full independent human
  semantic review beyond the acceptance testing described in
  `docs/chatbot/COMPLETION_REPORT.md` — treat answers as a strong starting
  point for verification against the cited source, not a substitute for
  reading it.

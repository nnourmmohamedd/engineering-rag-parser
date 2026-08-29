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
   `[S1]`. Click it — or click the matching source card below the
   answer — to open the source viewer: the exact page, jumped to
   automatically, with the supporting passage highlighted whenever the
   parser's coordinates or a text match make that possible (see "Opening
   a citation's source" below). The card itself also shows the source
   filename, page number, section heading, chunk id, and the exact
   supporting quote the model was validated against.
6. If the selected documents don't contain enough evidence, you get an
   explicit refusal — never a fabricated or unsupported answer.
7. A claim needing more than one supporting passage carries more than
   one marker (e.g. `[S1][S2]`) — the answer only cites as many passages
   as a claim genuinely needs, never padded for appearance, and never
   fewer than it needs: an answer with an uncited claim fails grounding
   validation and is refused rather than shown.

## Opening a citation's source

Click any `[S<n>]` marker in the answer, or a source card's **Open
source** button, to open the PDF viewer:

- It jumps straight to the cited page in the original PDF.
- When the parser recorded exact coordinates for that passage, they're
  highlighted directly. Otherwise, the viewer finds the model's
  quoted text in the page itself and highlights that. For a genuinely
  scanned or image-only page where neither is possible, the page still
  opens and the verified quotation is shown alongside it with an honest
  note that an exact visual highlight isn't available — the location and
  quote are never guessed.
- If more than one citation supports the current answer, use the
  prev/next controls in the viewer's header to step through all of them
  without closing the viewer.
- Zoom and page-navigation controls, and an **Open source** link to the
  raw PDF, are always available. Escape closes the viewer and returns
  you to exactly where you were in the conversation — nothing about your
  question, the answer, or your scroll position is lost.
- If a cited document has since been deleted, the viewer says so plainly
  and still shows the preserved quotation — the citation itself is never
  rewritten (see "Deleting a document" below).

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
- **Exact highlighting isn't always possible.** A scanned or image-only
  page has no selectable text layer, so neither a parser-recorded
  coordinate nor a text match can locate the passage on the page image
  itself — the viewer still jumps to the correct page and shows the
  verified quotation, with an honest notice rather than a guessed
  highlight. A chunk produced by splitting an oversized passage or
  merging two adjacent ones is also never highlighted with false
  precision: its recorded coordinates (if any) cover the whole original
  passage, not the specific cited sentence, so the viewer falls back to
  the text match instead of drawing a box that's technically present but
  wrong.
- **Documents indexed before this feature existed** (including this
  application's own original demonstration corpus) have no stored
  coordinate data at all — every citation into them uses the text-match
  highlight, never a coordinate one. This is expected, not a bug: nothing
  about their previously-indexed content was rebuilt or touched to add
  this feature.

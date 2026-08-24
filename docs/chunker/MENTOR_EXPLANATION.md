# Chunker: Explanation for Review

A short, direct account of the design decisions behind the chunking
milestone, written for a technical reviewer who has not read the code.

## Why hierarchical chunking comes first

A PDF (via Docling's `document.json`) already has real structure: headings,
sections, tables, lists, figures, reading order. Throwing that away and
starting from a flat wall of Markdown text — then re-discovering paragraph
boundaries with a generic splitter — is strictly worse than using the
structure Docling already extracted. `services/chunker/hierarchical.py`
wraps Docling's own `HierarchicalChunker`, which walks the document tree and
emits one chunk per structural unit (a paragraph, a table, a list), each
carrying its own heading path. This gives every chunk real document context
*before* any size-based decision is made.

## Why recursive splitting is conditional, not automatic

Most hierarchical chunks already fit inside an embedding model's context
window — a paragraph is usually a few dozen tokens. Recursive splitting only
activates for the minority of TEXT chunks that measure over `max_tokens`
(`services/chunker/recursive.py::split_oversized_text_chunk` returns the
chunk unchanged, unmeasured cost, when it already fits). Splitting text that
is already small enough would add arbitrary chunk boundaries with no
benefit — every extra chunk is extra index size and one more chance for a
retrieval query to miss context.

## Why generic recursive splitting is unsafe for tables/figures

A table's meaning depends on which column header a value belongs to; a
generic character/paragraph splitter has no concept of "row" or "column
header" and would produce cut lines like `"FT-101 | 0-1"` with the rest of
the row severed. A figure has no text at all to split — a splitter given an
image placeholder would either drop it silently or emit a meaningless
fragment. This is why every content type has its own handler
(`type_handlers/`): tables split by row group with the header repeated
(`tables.py`), lists split between items (`lists.py`), code splits on line
boundaries only, equations are never split at all
(`equations.py` — an equation cut in half is not a smaller equation, it is
corrupted data), and figures are recovered as their own atomic unit
(`figures.py`). See `HYBRID_BASELINE_COMPARISON.md` for concrete evidence of
what a generic-only approach (Docling's `HybridChunker`) misses here: it
silently drops the same captionless figures and uncaptioned raster tables
this project explicitly recovers, and produced one unflagged oversized chunk
in this comparison's own OCR-document run.

## How tokenizer-aware limits work

Every size decision — "does this chunk fit", "how much room is left for a
table header" — is made by encoding text with the *actual* tokenizer of the
target embedding model (`services/chunker/tokenizer.py`, wrapping
`transformers.AutoTokenizer`), never by counting characters or words. A
chunk that "fits" is guaranteed to fit the model that will eventually encode
it, not just look short. The tokenizer is fully configurable
(`config.tokenizer.name`) so swapping the future embedding model only means
changing one config value, not touching chunking logic. See
`CONFIGURATION.md` for why the default (`all-MiniLM-L6-v2`, `max_tokens=256`)
was chosen — a small, free, Apache-2.0 English sentence-embedding model whose
own trained `max_seq_length` is 256.

## How provenance is preserved

Every chunk carries `page_numbers`, `provenance` (page + bounding box +
character span), and `source_element_refs` (the underlying Docling
`self_ref` values) straight from the source `DoclingDocument` — the same
provenance the parser itself preserves in `document.json`. When the parser
already flagged something about the underlying element (an unrecovered
raster table, a diagram needing human review), that finding is carried
forward verbatim into `parser_warnings` on the chunk
(`type_handlers/tables.py::_propagate_parser_table_warnings`,
`type_handlers/figures.py`) — a downstream consumer never has to re-derive
what the parser already knew.

## How this prepares chunks for embeddings, a vector database, and reranking

`chunks.jsonl` is deliberately the full extent of this milestone's output —
no embedding is computed, no vector database is touched, nothing is indexed.
What it *does* provide, precisely because it stops here:

- **`retrieval_text`** is exactly what an embedding call would encode —
  ready to pass to any embedding model's API/library without further
  preprocessing.
- **`chunk_id`** is stable and deterministic, suitable as a primary key in a
  future vector store (ChromaDB or otherwise) without needing a separate ID
  generation step.
- **`content_type` / `table_metadata` / `figure_asset_path`** give a future
  retrieval or reranking stage a basis for type-aware ranking (e.g.
  preferring a TABLE chunk for a numeric-lookup query) without re-parsing
  the source document.
- **`heading_path` / `previous_chunk_id` / `next_chunk_id`** let a future
  reranker or generation prompt pull neighbouring context around a retrieved
  chunk, which a cross-encoder reranker commonly needs.

None of embeddings, ChromaDB, retrieval, or reranking is implemented here —
by explicit instruction. This document exists so the next milestone can
build directly on `chunks.jsonl` without re-deriving any of the above.

## Difference from Docling's `HybridChunker`

`HybridChunker` also does structure-first-then-token-aware chunking — the
two are close cousins conceptually. The concrete differences, backed by
`HYBRID_BASELINE_COMPARISON.md`'s real-document evidence:

1. **Content-type awareness.** `HybridChunker` emits undifferentiated text
   spans; this project's chunks carry `content_type`, `table_metadata`,
   `figure_asset_path`.
2. **Element recovery.** Both wrap the same `HierarchicalChunker`
   underneath, which drops captionless figures and uncaptioned raster
   tables. This project explicitly recovers both
   (`type_handlers/tables.py::build_uncovered_table_chunks`,
   `type_handlers/figures.py::build_figure_chunks`); `HybridChunker` does
   not.
3. **Explicit overflow flagging.** `is_atomic_overflow` is a first-class
   output field here; `HybridChunker` only warns via Python's `warnings`
   module and, in this comparison, produced one unflagged chunk over
   `max_tokens` on the OCR benchmark document.
4. **Parser-warning propagation.** This project threads the parser's own
   `validation/report.json` findings into chunk-level `parser_warnings`;
   `HybridChunker` has no such integration (it has never seen the parser).
5. **Validation and run artifacts.** This project produces a full
   `validation_report.json`, `manifest.json` and immutable run directory;
   `HybridChunker` is a library call with no artifact layer.

`HybridChunker` remains a legitimate, faster alternative for a use case that
does not need type-aware splitting or artifact/validation infrastructure —
that trade-off is stated plainly, not dismissed.

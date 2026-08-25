# Indexing: Explanation for Review

A short, direct account of the design decisions behind the embedding +
ChromaDB indexing milestone, written for a technical reviewer who has not
read the code.

## Why the chunker had to be rerun before this milestone could start

The chunker milestone's default profile sized chunks against
`sentence-transformers/all-MiniLM-L6-v2`'s tokenizer (256-token budget) —
the correct choice at the time, since no embedding model had been selected
yet. This milestone's embedding model, `BAAI/bge-base-en-v1.5`, uses a
different tokenizer and supports up to 512 tokens. Two different tokenizers
count the same text as a different number of tokens, so a chunk that "fit"
under MiniLM's counting is not guaranteed to fit under BGE's — silently
trusting the old chunk runs risked truncation the chunker itself never
signalled. Rather than patch around this, the correct fix was to treat it as
what it is: an input-compatibility problem, caught explicitly rather than
worked around. `configs/chunker_bge.yaml` reruns the existing, unmodified
chunker architecture with BGE's own tokenizer and 512-token budget; the
original MiniLM-sized runs are preserved untouched (they remain valid
input for a MiniLM-based ordering, just not for this milestone). See
`EMBEDDING_MODEL_DECISION.md` and `VALIDATION.md` gate 3 for the mechanism
that makes this compatibility requirement enforced, not just documented —
a tokenizer mismatch is a hard rejection at indexing time, not a warning.

## Why the embedder and Chroma adapter never import each other's libraries

`services/embedder/` never imports `chromadb`; `databases/chroma/` never
imports `sentence-transformers`. This is not a style preference — it means
either piece is independently testable (the Chroma adapter's tests never
need a real embedding model; the embedder's tests never need a running
database) and independently replaceable (a future different vector database,
or a future different embedding model, touches exactly one package). The
indexing pipeline is the single, deliberately thin place that wires the two
together.

## Why passages get no prefix but queries do

BGE-base-en-v1.5's own model card specifies this asymmetry: the model was
*trained* with queries prefixed by an instruction string
(`"Represent this sentence for searching relevant passages: "`) and passages
left bare. This is not an arbitrary implementation choice — embedding a
passage with the query prefix, or a query without it, would feed the model
input unlike what it was trained on and measurably degrade retrieval
quality. `services/embedder/bge.py::embed_passages()` never applies the
query prefix; `embed_query()` always does, and rejects an empty/whitespace
query outright rather than embedding a meaningless instruction-only string.

## Why every retrieval_text is re-measured, not trusted from the chunker

The chunker's stored `token_count` was measured with *its own* configured
tokenizer for its own size-budget decisions — under `configs/chunker_bge.yaml`
that happens to be BGE's tokenizer too, but the indexing pipeline does not
assume that will always be true of every future chunk run it is pointed at.
`pipelines/indexing_pipeline.py::_oversized_chunk_ids()` independently
re-encodes every `retrieval_text` with the *embedding* model's own tokenizer
before admitting a chunk run, and any chunk over `maximum_sequence_length`
is a hard rejection — never a silent truncation inside
`sentence-transformers`' own tokenization step, which would otherwise cut
text without any signal that it happened.

## Why idempotency is content-hash-based, not just id-based

Reindexing the same input twice must never duplicate — but it also must
never silently accept a *different* chunk under an id that was already
written, since that would corrupt the mapping from `chunk_id` back to its
canonical `chunks.jsonl` row. `content_hash()`
(`databases/chroma/repository.py`) hashes the passage text plus its key
metadata and stores it alongside the vector; a rerun with an unchanged hash
under the same id is recognized as a genuine no-op and skipped, while a
changed hash under the same id is treated as a data-integrity problem and
raises `DuplicateIdConflictError` rather than overwriting. This was verified
end-to-end on the real corpus (see `INDEXING_COMPLETION_REPORT.md`'s
idempotency evidence): reindexing the 113-chunk engineering-document run a
second time inserted 0 new records, recognized all 113 as already-identical,
and left the collection count unchanged at 122.

## Why `smoke-query` exists but is explicitly not the retrieval API

Storing 122 vectors that are never queried proves nothing about whether the
storage actually worked end-to-end. `smoke-query` exists purely to close
that loop — it is a genuine ChromaDB similarity search over real,
production-embedded vectors, not a mock. But it has no reranking, no hybrid
lexical search, no filtering, and no relevance-quality claim attached to it;
its own CLI output prints a `DIAGNOSTIC` banner every time it runs. Building
the actual retrieval service — the thing an end user would query — is
explicitly the next milestone.

## What this milestone hands to the next one

- A persistent, versioned-identity Chroma collection at
  `data/output/databases/chroma/engineering_documents_v1`, containing every
  chunk from both real source documents (122 records total), each traceable
  back to its full canonical `chunks.jsonl` row via `chunk_id`.
- A proven-idempotent, proven-compatible ingestion path — a future document
  can be added to the same collection by running the chunker with
  `configs/chunker_bge.yaml` and then `engrag-index build`, with no manual
  bookkeeping.
- Every embedding-relevant identity fact (model name, resolved revision,
  tokenizer, dimension, distance metric) recorded in both the collection's
  own Chroma metadata and every run's `index_manifest.json`, so a future
  retrieval milestone never has to guess what produced the vectors it is
  querying.

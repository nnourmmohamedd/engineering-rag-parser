# `services/retriever`

Domain retrieval logic and data contracts for vector search over an already-
indexed ChromaDB collection, plus (this milestone) optional BM25 fusion and
the orchestration contracts hybrid search is built from. This package never
imports `chromadb` or `bm25s` directly — `VectorRetriever` is handed an
already-opened collection object and an `EmbeddingService`, and
`BM25Retriever` is handed an already-loaded `BM25IndexHandle`
(`databases/bm25`), by their caller (`pipelines/retrieval_pipeline.py`,
specifically its `HybridRetriever` orchestrator).

## Contents

- `models.py` — `RetrievalRequest`, `RetrievalHit` (now also carrying
  `vector_rank`/`bm25_rank`/`bm25_score`/`rrf_rank`/`rrf_score`/
  `reranker_rank`/`reranker_score`, all `None` in vector-only responses),
  `RetrievalResponse` (now also carrying `retrieval_mode`, `bm25_enabled`,
  `reranker_enabled`, `candidate_counts`, `stage_latencies_s`), and the
  evaluation contracts (`RetrievalEvaluationCase/Result/Summary`).
- `config.py` — `RetrievalSearchConfig` (top-k limits, allowed metadata
  filter fields, timeouts), `RetrievalModeConfig` (vector/BM25 toggles and
  candidate pool sizes), `FusionConfig` (RRF constant), and
  `RetrievalEvaluationConfig` (dataset path, K values, output root).
- `errors.py` — typed exception vocabulary
  (`CollectionNotFoundError`, `EmptyCollectionError`, `InvalidFilterError`,
  `MalformedChromaResponseError`).
- `filters.py` — validates and translates caller metadata filters into a
  Chroma `where` clause; rejects JSON-encoded list fields explicitly.
- `retriever.py` — `VectorRetriever.search()`: the core embed → query →
  provenance-preserving-hits flow. Also defines `SearchableRetriever`, the
  structural protocol both `VectorRetriever` and `HybridRetriever`
  (`pipelines/retrieval_pipeline.py`) satisfy, so the evaluation runner never
  branches on which mode is active.
- `bm25_retriever.py` — `BM25Retriever.search()`: scores the entire injected
  BM25 index against a query and applies the same scalar metadata filters as
  Chroma, client-side (documented limitation — see the module docstring).
- `fusion.py` — `reciprocal_rank_fusion()`: combines a vector ranking and a
  BM25 ranking by rank position only, never by mixing raw scores.
- `corpus_compat.py` — `check_corpus_compatibility()` /
  `require_compatible()`: the strict gate that refuses to fuse a Chroma
  collection against a BM25 index built from a different corpus version.
- `evaluation/` — the evidence-based retrieval benchmark: ground-truth
  dataset loader, closed-form metrics (no LLM judge), and the run orchestrator
  (now mode-aware: `retrieval_mode`/`bm25_enabled`/`reranker_enabled` are
  recorded on every `RetrievalEvaluationSummary`).

## Design rules this package follows

1. **No hidden Chroma client.** `VectorRetriever.__init__` takes a
   `collection` object; it is never constructed here.
2. **No embedding duplication.** Query embedding is delegated entirely to the
   injected `EmbeddingService` (`services/embedder`), reusing the exact BGE
   query-instruction handling already validated by the indexing milestone.
3. **Never creates or mutates a collection.** Every method here only reads.
4. **Honest distance/similarity.** `raw_distance` is always Chroma's native
   value; `similarity_score` is populated only when the collection's stored
   `distance_metric` is verified `cosine` (`similarity = 1 - distance`).
5. **Dependency injection everywhere.** Unit tests use a fake embedder, a
   fake reranker (`tests/support/fake_reranker.py`), and a real, ephemeral,
   `tmp_path`-rooted Chroma collection / BM25 index — never a mock of Chroma
   or bm25s query semantics.
6. **BM25 never mutates its index during search**, and hybrid search never
   fuses two incompatible corpora — `require_compatible()` raises before any
   query runs if the live Chroma collection and the persistent BM25 index
   disagree on record count, chunk ids, document ids, filenames, content
   hashes, or schema version.

See `docs/retrieval/ARCHITECTURE.md` for the vector-only pipeline diagram,
`docs/retrieval/HYBRID_RETRIEVAL_ARCHITECTURE.md` for the hybrid + reranking
pipeline, and `docs/retrieval/EVALUATION.md` for the metrics and dataset
methodology.

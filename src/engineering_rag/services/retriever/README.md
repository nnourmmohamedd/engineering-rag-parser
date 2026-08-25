# `services/retriever`

Domain retrieval logic and data contracts for vector search over an already-
indexed ChromaDB collection. This package never imports `chromadb` and never
constructs its own client — `VectorRetriever` is handed an already-opened
collection object and an `EmbeddingService` by its caller
(`pipelines/retrieval_pipeline.py`).

## Contents

- `models.py` — `RetrievalRequest`, `RetrievalHit`, `RetrievalResponse`,
  `RetrievalDiagnostics`, and the evaluation contracts
  (`RetrievalEvaluationCase/Result/Summary`).
- `config.py` — `RetrievalSearchConfig` (top-k limits, allowed metadata
  filter fields, timeouts) and `RetrievalEvaluationConfig` (dataset path, K
  values, output root).
- `errors.py` — typed exception vocabulary
  (`CollectionNotFoundError`, `EmptyCollectionError`, `InvalidFilterError`,
  `MalformedChromaResponseError`).
- `filters.py` — validates and translates caller metadata filters into a
  Chroma `where` clause; rejects JSON-encoded list fields explicitly.
- `retriever.py` — `VectorRetriever.search()`: the core embed → query →
  provenance-preserving-hits flow.
- `evaluation/` — the evidence-based retrieval benchmark: ground-truth
  dataset loader, closed-form metrics (no LLM judge), and the run orchestrator.

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
5. **Dependency injection everywhere.** Unit tests use a fake embedder and a
   real, ephemeral, `tmp_path`-rooted Chroma collection — never a mock of
   Chroma's query semantics.

See `docs/retrieval/ARCHITECTURE.md` for the full pipeline diagram and
`docs/retrieval/EVALUATION.md` for the metrics and dataset methodology.

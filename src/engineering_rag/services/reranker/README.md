# `services/reranker`

Cross-encoder reranking: joint query-document scoring of a small candidate
set, independent of both `services/retriever` and `databases/chroma`/`bm25`.

## Contents

- `config.py` — `RerankerConfig` (`enabled` — off by default, model
  name/revision, `candidate_top_k`/`final_top_k`, batch size, max length,
  device). Validates `candidate_top_k >= final_top_k`.
- `models.py` — `RerankCandidate` (chunk_id + text), `RerankResult`
  (chunk_id + rank + raw score).
- `interface.py` — the `Reranker` protocol
  (`rerank(query, candidates) -> list[RerankResult]`), so
  `tests/support/fake_reranker.py` and the production `CrossEncoderReranker`
  are interchangeable everywhere.
- `cross_encoder.py` — `CrossEncoderReranker`: loads
  `BAAI/bge-reranker-base` via `sentence_transformers.CrossEncoder` (already
  a dependency under the `indexing` extra — no new package). Loaded lazily,
  only when `reranker.enabled: true`; logs load time and per-query inference
  latency; never applies the BGE embedding query prefix (the cross-encoder's
  official usage does not require it).

## Score honesty

`RerankResult.score` is the model's raw (sigmoid-activated) output — a
relative ranking signal, **not** a calibrated probability of relevance. This
is stated in the model docstring, the field docstring, and
`docs/retrieval/HYBRID_RETRIEVAL_ARCHITECTURE.md` — never presented as a
probability anywhere in this codebase.

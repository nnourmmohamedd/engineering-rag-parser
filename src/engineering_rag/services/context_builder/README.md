# `services/context_builder`

Turns one retrieval response into a budgeted, citable `ContextPackage`:
deduplicate → apply per-document/per-section diversity limits while token-
budgeting in ranked order → optional same-document neighbor expansion (fills
only leftover budget) → assign citation IDs → render sanitized `<SOURCE>`
blocks.

Pure domain logic: no `chromadb` import, no `clients.ollama` import. A
concrete `NeighborProvider` (Chroma-backed) is injected by
`pipelines/answering_pipeline.py`, the only module that constructs one.

See `docs/answering/GROUNDED_ANSWERING_ARCHITECTURE.md` for the full
selection algorithm and the token-budget rationale.

## Token counting

`TokenCounter` is an interface with two implementations:

- `Qwen3TokenCounter` (default): exact counts under the real
  `Qwen/Qwen3-8B` tokenizer (tokenizer files only, ~a few MB — never the
  model weights).
- `ConservativeFallbackTokenCounter`: a deterministic, network-free
  character-count heuristic that always over-counts relative to observed
  Qwen3 tokenization on this project's text. Explicitly **not** exact —
  `TokenCounter.is_exact` is `False` for it.

## Never split a chunk

A single chunk whose token count alone exceeds `max_context_tokens` is
excluded whole (`chunk_exceeds_budget_alone`) rather than truncated — there
is no safe truncation fallback implemented in this version.

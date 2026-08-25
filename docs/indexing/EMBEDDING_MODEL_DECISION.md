# Embedding Model Decision

## Chosen

**`BAAI/bge-base-en-v1.5`**, via `sentence-transformers`.

- 768-dimensional output.
- 512-token maximum sequence length (its own trained `max_seq_length`).
- MIT licensed, ~109M parameters.
- Resolved commit revision at the time of this milestone's verification:
  `a5beb1e3e68b9ab74eb54cfd186867f64f240e1a` (from the local Hugging Face
  Hub cache's `refs/main`, re-verified independently rather than assumed —
  see `services/embedder/bge.py::_resolve_revision`, which records this
  automatically in every `index_manifest.json`).

## Why

- **English documents.** This project's corpus (engineering PDFs) is English;
  a general multilingual model would spend capacity on languages never used.
- **512-token compatibility.** Matches the chunker's practical chunk sizes
  once sized for this model (`configs/chunker_bge.yaml`, `max_tokens: 512`)
  without needing an unusually long-context model.
- **768 dimensions.** A well-established middle ground — enough representational
  capacity for retrieval quality, without the storage/compute cost of a
  1024-d+ model at this corpus scale.
- **Local, private.** Runs entirely on-device via `sentence-transformers`; no
  document content leaves the machine, no paid API, no network dependency
  after the model is cached.
- **Good quality/resource balance.** BGE-base consistently ranks near the top
  of open English retrieval benchmarks (MTEB) among CPU-friendly base-sized
  models, without requiring GPU hardware this project does not assume.
- **Suitable for later reranking.** A future cross-encoder reranking stage
  (explicitly out of scope for this milestone) commonly re-scores a first-stage
  retriever's candidates; BGE-base is a standard, well-supported first-stage
  retriever for that pairing (e.g. `BAAI/bge-reranker-base` is trained to be
  paired with BGE embedding models specifically).

## Alternatives considered

| Model | Trade-off |
|---|---|
| `BAAI/bge-small-en-v1.5` | Faster and smaller (384-d), but a lower-quality baseline — appropriate for a resource-constrained deployment, not the production baseline chosen here. |
| `BAAI/bge-m3` | Multilingual and long-context (up to 8192 tokens), but substantially heavier (more parameters, larger memory footprint) for a corpus that is presently English-only. |
| `sentence-transformers/all-MiniLM-L6-v2` | Fast and free (already used as the chunker's default sizing tokenizer), but a general-purpose sentence-similarity model, not tuned for retrieval the way BGE's `bge-*` family explicitly is — less appropriate as the production embedding baseline. |

## Do not change to

BGE-small, BGE-large, BGE-M3, MiniLM, OpenAI embeddings, or any other model,
**unless a genuine incompatibility is proven and reported first** — per this
milestone's explicit instruction. `services/embedder/config.py`'s
`model_name` field remains configurable (so a documented future change is a
one-line config edit, not a code change), but `BAAI/bge-base-en-v1.5` is the
required production default and `configs/indexing_production.yaml` pins it.

## Future reconsideration triggers

- The corpus becomes genuinely multilingual (e.g. Arabic engineering
  documents) — BGE-base-en is English-tuned and would need to be replaced
  with `bge-m3` or an equivalent multilingual model.
- Hardware constraints change (e.g. deployment to a much smaller device where
  even BGE-base's CPU inference cost is prohibitive) — `bge-small` would be
  the natural fallback, with an explicit quality trade-off documented.
- A future retrieval-evaluation milestone (explicitly out of scope here)
  produces evidence that BGE-base's retrieval quality is insufficient for
  this corpus — any such change requires that evaluation evidence first, not
  a preference.

## What this milestone does NOT claim

Choosing BGE-base-en-v1.5 as a sound production default is not a claim about
retrieval accuracy on this specific corpus — no semantic-quality evaluation
was performed here (see `VALIDATION.md`'s explicit "semantic smoke test vs.
hard gate" separation). That evaluation is the next milestone's scope.

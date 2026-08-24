# `services/chunker` — structure-aware chunking service

**Implemented.** Hierarchical-first, tokenizer-aware, conditionally-recursive
chunking of parser-produced `document.json` into retrieval-ready
`chunks.jsonl`. Full documentation: [`docs/chunker/`](../../../../docs/chunker/).

## Quick start

```powershell
.\.venv\Scripts\engrag-chunk.exe run `
  --input "data\output\parser\<document>\<run-id>" `
  --profile configs\chunker_production.yaml
```

## Public interface

```python
from engineering_rag.services.chunker import ChunkerConfig, ChunkerRequest, ChunkerResult, ChunkerService

result = ChunkerService().run(ChunkerRequest(input_path=..., config=ChunkerConfig()))
```

See `docs/chunker/ARCHITECTURE.md` for the pipeline, `OUTPUT_SCHEMA.md` for
the `chunks.jsonl` contract, `CONFIGURATION.md` for every parameter, and
`MENTOR_EXPLANATION.md` for the design rationale.

## What this milestone does not do

No embedding generation, no vector database (ChromaDB or otherwise), no
retrieval, no reranking, no chatbot — this milestone ends at validated,
retrieval-ready chunk records. See
`docs/chunker/MENTOR_EXPLANATION.md#how-this-prepares-chunks-for-embeddings-a-vector-database-and-reranking`
for how `chunks.jsonl` is shaped to make that next milestone straightforward
without re-deriving anything from the source PDF.

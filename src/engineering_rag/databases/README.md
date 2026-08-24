# `databases` — future storage boundary, not implemented

This is where a future ChromaDB (or other vector store) client, a metadata
store, and repository interfaces for persisted chunks/embeddings will live.

Nothing here today. ChromaDB is not installed and no persistence adapter
exists — the parser milestone's outputs are plain files under
`data/output/parser/`. This package exists only so the dependency boundary
(`services -> databases`, never the reverse) is visible in the architecture
before the retrieval milestone starts.

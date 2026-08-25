# `databases` — persistence boundary

`databases/chroma/` is the ChromaDB storage adapter used by the embedding
milestone (`services/embedder/` + `pipelines/indexing_pipeline.py`). It
accepts plain `list[float]` vectors and never imports `sentence-transformers`
— the dependency boundary is `services -> databases`, never the reverse, and
`databases/chroma/` never imports anything under `services/`.

See `databases/chroma/__init__.py` for the public surface, and
`docs/indexing/` (added by the embedding milestone) for the full architecture
writeup.

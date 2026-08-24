# `clients` — future external-service boundary, not implemented

This is where a future embedding-model client, reranker client, LLM client,
or any other remote model endpoint will live. Each client should be a thin,
typed adapter that a service (e.g. the future embedder/retriever/reranker
services) depends on — never the other way around.

Nothing here today: the current parser milestone is entirely local-first and
makes no outbound network calls (`docling.enable_remote_services` is pinned
to `False` by a config validator). No fake or placeholder client is added
until a real integration needs one.

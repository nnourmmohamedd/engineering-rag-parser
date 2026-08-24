"""``engineering_rag``: a service-oriented, local-first document ingestion project.

Today the only implemented capability is the PDF parser
(:mod:`engineering_rag.services.parser`), reachable through
:mod:`engineering_rag.pipelines.parsing_pipeline` and the ``engrag-parse`` CLI
(:mod:`engineering_rag.api.cli`). Chunking, embeddings, vector storage,
retrieval, reranking and an API server are explicitly not implemented yet —
see ``docs/architecture/service_architecture.md`` for the full picture and
``services/chunker/README.md`` for the next milestone's contract.
"""

from __future__ import annotations

__all__ = ["__version__"]

#: Package version. Also recorded as ``parser_version`` in every run manifest
#: via :data:`engineering_rag.services.parser.PARSER_VERSION`.
__version__ = "1.0.0"

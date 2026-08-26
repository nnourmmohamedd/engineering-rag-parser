"""Local document-ingestion chatbot: durable registry, ingestion orchestration and HTTP API.

This package is an ``api``-tier component in the repository's enforced
dependency direction (``api -> pipelines -> services -> utils``, see
``pipelines/__init__.py``). It orchestrates the *existing* production
pipelines and must never duplicate parsing, chunking, embedding, indexing,
retrieval, reranking or answering logic, nor reach past a pipeline into a
service's internals.

Everything here is designed for a single local user: the API binds to
``127.0.0.1`` by default and ships no authentication. Remote exposure would
require authentication and HTTPS first -- see ``docs/chatbot/SECURITY.md``.
"""

from __future__ import annotations

from engineering_rag import __version__

__all__ = ["CHATBOT_VERSION"]

CHATBOT_VERSION = __version__

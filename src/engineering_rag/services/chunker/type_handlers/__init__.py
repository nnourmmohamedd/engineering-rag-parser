"""Type-specific chunk refinement: tables, lists, code, equations, figures.

Each handler receives one hierarchical :class:`~engineering_rag.services.chunker.internal.WorkingChunk`
of its content type and returns one or more refined chunks. None of them
route content through a generic character splitter — that is reserved for
:mod:`engineering_rag.services.chunker.recursive`, and only for TEXT.
"""

from __future__ import annotations

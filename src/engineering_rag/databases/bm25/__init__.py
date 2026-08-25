"""Persistent BM25 lexical index adapter.

The only place in this package tree that imports ``bm25s``. Mirrors
``databases/chroma``'s shape: a validated config, typed models, and
build/load/search functions that never mutate the on-disk index during a
search. BM25 never creates chunks — it indexes the exact same
``retrieval_text``/``chunk_id`` records the vector index was built from (see
``pipelines/retrieval_pipeline.py::read_chroma_corpus_as_bm25_records``).
"""

from __future__ import annotations

from .config import BM25Config
from .errors import BM25Error, BM25IndexNotFoundError, CorpusValidationError
from .index import BM25IndexHandle, build_bm25_index, load_bm25_index
from .models import (
    BM25_INDEX_SCHEMA_VERSION,
    BM25CorpusRecord,
    BM25Manifest,
    BM25RawHit,
    BM25ValidationCheck,
    BM25ValidationReport,
)
from .tokenizer import TOKENIZER_VERSION, tokenize, tokenize_corpus

__all__ = [
    "BM25_INDEX_SCHEMA_VERSION",
    "TOKENIZER_VERSION",
    "BM25Config",
    "BM25CorpusRecord",
    "BM25Error",
    "BM25IndexHandle",
    "BM25IndexNotFoundError",
    "BM25Manifest",
    "BM25RawHit",
    "BM25ValidationCheck",
    "BM25ValidationReport",
    "CorpusValidationError",
    "build_bm25_index",
    "load_bm25_index",
    "tokenize",
    "tokenize_corpus",
]

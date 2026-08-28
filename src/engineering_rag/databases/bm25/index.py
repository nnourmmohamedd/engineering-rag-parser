"""Persistent BM25 lexical index: build once, load and search many times.

Backed by ``bm25s`` (MIT-licensed, pure-Python + numpy, no server, no
network at query time — https://github.com/xhluca/bm25s). This module never
imports ``chromadb``: it is handed an already-read list of
:class:`~engineering_rag.databases.bm25.models.BM25CorpusRecord` by its
caller (``pipelines/retrieval_pipeline.py``, the only module that reads both
the live Chroma collection and this index), mirroring how
``services/retriever/retriever.py`` never imports ``chromadb`` directly.

Search never rebuilds or mutates the on-disk index: ``load_bm25_index``
opens it read-only (optionally memory-mapped) and ``BM25IndexHandle.search``
only calls ``BM25.retrieve``.
"""

from __future__ import annotations

import logging
import shutil
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version as pkg_version
from pathlib import Path

from .config import BM25Config
from .errors import BM25IndexNotFoundError, CorpusValidationError
from .models import BM25CorpusRecord, BM25Manifest, BM25RawHit
from .tokenizer import TOKENIZER_VERSION, tokenize_corpus

__all__ = ["BM25IndexHandle", "build_bm25_index", "load_bm25_index"]

logger = logging.getLogger(__name__)

_MANIFEST_FILENAME = "bm25_manifest.json"
_VALIDATION_FILENAME = "bm25_validation_report.json"


def _validate_corpus(records: list[BM25CorpusRecord]) -> list[str]:
    """Raise :class:`CorpusValidationError` on any hard defect; return soft warnings otherwise."""
    warnings: list[str] = []
    seen_ids: set[str] = set()
    duplicates: list[str] = []
    malformed: list[str] = []

    for record in records:
        if record.chunk_id in seen_ids:
            duplicates.append(record.chunk_id)
        seen_ids.add(record.chunk_id)
        if not record.retrieval_text or not record.retrieval_text.strip():
            malformed.append(record.chunk_id)

    if duplicates:
        raise CorpusValidationError(f"duplicate chunk_id(s) in source corpus: {sorted(set(duplicates))}")
    if malformed:
        raise CorpusValidationError(f"missing/empty retrieval_text for chunk_id(s): {sorted(malformed)}")

    missing_hash = [r.chunk_id for r in records if not r.content_hash]
    if missing_hash:
        warnings.append(f"{len(missing_hash)} record(s) missing content_hash: {missing_hash[:5]}...")
    return warnings


def _corpus_fingerprint(records: list[BM25CorpusRecord]) -> str:
    """Deterministic fingerprint independent of input ordering."""
    pairs = sorted((r.chunk_id, r.content_hash or "") for r in records)
    payload = "\n".join(f"{cid}:{chash}" for cid, chash in pairs)
    return sha256(payload.encode("utf-8")).hexdigest()


def build_bm25_index(
    records: list[BM25CorpusRecord],
    config: BM25Config,
    *,
    collection_name: str,
    chroma_persistence_path: str,
    force: bool = False,
) -> BM25Manifest:
    """Build a persistent BM25 index from ``records`` and atomically replace any existing one.

    Idempotent: if a valid index already exists at ``config.index_path`` with
    the identical ``corpus_fingerprint``, the build is skipped entirely (no
    file is touched, the existing manifest is returned unchanged) unless
    ``force=True``. This is both the cheap no-op path for "nothing changed,
    rebuild anyway" re-runs and the safest one on platforms (Windows) where a
    directory holding memory-mapped files cannot always be replaced while a
    reader has it open elsewhere in the same process.

    A failed build never touches a previously valid index at
    ``config.index_path`` — the new index is built in a sibling temporary
    directory and only swapped in on success.

    Raises:
        CorpusValidationError: duplicate chunk ids, or missing/empty text.
    """
    import bm25s

    started = time.perf_counter()
    warnings = _validate_corpus(records)

    new_fingerprint = _corpus_fingerprint(records)
    if not force:
        existing_manifest_path = Path(config.index_path) / _MANIFEST_FILENAME
        if existing_manifest_path.is_file():
            existing = BM25Manifest.model_validate_json(existing_manifest_path.read_text(encoding="utf-8"))
            if (
                existing.corpus_fingerprint == new_fingerprint
                and existing.method == config.method
                and existing.k1 == config.k1
                and existing.b == config.b
                and existing.tokenizer_version == TOKENIZER_VERSION
            ):
                logger.info(
                    "BM25 index at %s already matches this corpus (fingerprint=%s); skipping rebuild",
                    config.index_path,
                    new_fingerprint[:12],
                )
                return existing

    tokenized = tokenize_corpus([r.retrieval_text for r in records])
    empty_after_tokenize = [r.chunk_id for r, toks in zip(records, tokenized, strict=True) if not toks]
    if empty_after_tokenize:
        warnings.append(
            f"{len(empty_after_tokenize)} record(s) tokenized to zero terms: {empty_after_tokenize[:5]}..."
        )

    bm25 = bm25s.BM25(k1=config.k1, b=config.b, method=config.method)
    bm25.index(tokenized, show_progress=False)

    corpus_payload = [record.model_dump(mode="json") for record in records]

    final_path = Path(config.index_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    build_path = final_path.parent / f"{final_path.name}.building-{uuid.uuid4().hex[:8]}"
    bm25.save(str(build_path), corpus=corpus_payload, allow_pickle=False, show_progress=False)

    manifest = BM25Manifest(
        generated_at_utc=datetime.now(timezone.utc),
        collection_name=collection_name,
        chroma_persistence_path=chroma_persistence_path,
        corpus_count=len(records),
        corpus_fingerprint=new_fingerprint,
        chunk_ids=sorted(r.chunk_id for r in records),
        document_ids=sorted({r.document_id for r in records if r.document_id}),
        source_filenames=sorted({r.source_filename for r in records if r.source_filename}),
        content_hashes={r.chunk_id: r.content_hash for r in records if r.content_hash},
        chunk_schema_versions=sorted({r.chunk_schema_version for r in records if r.chunk_schema_version}),
        bm25_library="bm25s",
        bm25_library_version=pkg_version("bm25s"),
        tokenizer_version=TOKENIZER_VERSION,
        method=config.method,
        k1=config.k1,
        b=config.b,
        index_creation_duration_s=round(time.perf_counter() - started, 4),
        warnings=warnings,
    )
    (build_path / _MANIFEST_FILENAME).write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    validation = {
        "status": "PASS",
        "checks": [
            {"check_id": "no_duplicate_chunk_ids", "passed": True, "summary": f"{len(records)} unique ids"},
            {"check_id": "no_missing_text", "passed": True, "summary": "every record has non-empty text"},
            {
                "check_id": "corpus_not_empty",
                "passed": len(records) > 0,
                "summary": f"corpus_count={len(records)}",
            },
        ],
    }
    (build_path / _VALIDATION_FILENAME).write_text(
        __import__("json").dumps(validation, indent=2), encoding="utf-8"
    )

    backup_path: Path | None = None
    if final_path.exists():
        backup_path = final_path.parent / f"{final_path.name}.previous-{uuid.uuid4().hex[:8]}"
        final_path.replace(backup_path)
    build_path.replace(final_path)
    if backup_path is not None:
        shutil.rmtree(backup_path, ignore_errors=True)

    logger.info(
        "Built BM25 index: %d record(s), fingerprint=%s, path=%s",
        manifest.corpus_count,
        manifest.corpus_fingerprint[:12],
        final_path,
    )
    return manifest


class BM25IndexHandle:
    """A loaded, read-only BM25 index ready to search. Never mutates the on-disk index."""

    def __init__(
        self, bm25: object, records_by_position: list[BM25CorpusRecord], manifest: BM25Manifest
    ) -> None:
        self._bm25 = bm25
        self._records = records_by_position
        self.manifest = manifest

    @property
    def records(self) -> tuple[BM25CorpusRecord, ...]:
        """Every indexed corpus record, read-only.

        Exposed so a caller can reconcile this index against Chroma (does each
        index hold the same chunks for a document?) without either reaching
        into private state or re-reading ``corpus.jsonl`` itself. Returned as a
        tuple so a caller cannot mutate the loaded corpus.
        """
        return tuple(self._records)

    def search(self, query: str, top_k: int) -> list[BM25RawHit]:
        """Rank every indexed document against ``query`` and return the top ``top_k``.

        Never rebuilds or writes to the index. An empty/whitespace query
        returns an empty result list rather than raising, mirroring a
        lexical index's natural behavior (no terms to match).
        """
        from .tokenizer import tokenize

        query_tokens = tokenize(query)
        if not query_tokens or not self._records:
            return []

        k = min(top_k, len(self._records))
        results, scores = self._bm25.retrieve(  # type: ignore[attr-defined]
            [query_tokens], k=k, corpus=None, show_progress=False
        )
        hits: list[BM25RawHit] = []
        for rank, (idx, score) in enumerate(zip(results[0], scores[0], strict=True), start=1):
            hits.append(BM25RawHit(bm25_rank=rank, bm25_score=float(score), record=self._records[int(idx)]))
        return hits


def load_bm25_index(config: BM25Config) -> BM25IndexHandle:
    """Load the persistent BM25 index at ``config.index_path``, read-only.

    Raises:
        BM25IndexNotFoundError: no index exists at the configured path.
    """
    import json

    import bm25s

    index_path = Path(config.index_path)
    manifest_path = index_path / _MANIFEST_FILENAME
    if not index_path.is_dir() or not manifest_path.is_file():
        raise BM25IndexNotFoundError(
            f"No BM25 index at {index_path}. Build one first with "
            "`engrag-retrieve build-bm25 --profile <profile>`."
        )

    manifest = BM25Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    bm25 = bm25s.BM25.load(str(index_path), load_corpus=False, mmap=config.mmap, allow_pickle=False)

    corpus_path = index_path / "corpus.jsonl"
    records: list[BM25CorpusRecord] = []
    with corpus_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(BM25CorpusRecord.model_validate(json.loads(line)))

    return BM25IndexHandle(bm25=bm25, records_by_position=records, manifest=manifest)


def duplicate_token_counts(tokens: list[str]) -> Counter[str]:
    """Test/debug helper: term frequency within one tokenized document."""
    return Counter(tokens)

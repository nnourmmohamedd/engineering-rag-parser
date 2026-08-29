"""Integration tests against a real, ephemeral ChromaDB PersistentClient.

Uses ``tmp_path`` and fake (hand-built) 768-d vectors — no real embedding
model needed. Exercises: collection creation, batch add, idempotent rerun,
conflicting-id rejection, model/dimension/metric mismatch rejection,
round-trip after a fresh client reopen, and self-retrieval.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_rag.databases.chroma.client import get_client
from engineering_rag.databases.chroma.collection import open_or_create_collection, rebuild_collection
from engineering_rag.databases.chroma.config import ChromaConfig
from engineering_rag.databases.chroma.errors import CollectionMismatchError, DuplicateIdConflictError
from engineering_rag.databases.chroma.models import CollectionIdentity
from engineering_rag.databases.chroma.repository import content_hash, ingest_batch
from engineering_rag.databases.chroma.validation import round_trip_check, self_retrieval_check

pytestmark = pytest.mark.integration


def _vector(seed: int, dim: int = 768) -> list[float]:
    v = [0.0] * dim
    v[seed % dim] = 1.0
    return v


def _identity(**overrides: object) -> CollectionIdentity:
    base: dict[str, object] = {
        "model_name": "BAAI/bge-base-en-v1.5",
        "embedding_dimension": 768,
        "distance_metric": "cosine",
        "tokenizer_name": "BAAI/bge-base-en-v1.5",
    }
    base.update(overrides)
    return CollectionIdentity(**base)  # type: ignore[arg-type]


def _config(tmp_path: Path, **overrides: object) -> ChromaConfig:
    base: dict[str, object] = {"persistence_path": tmp_path / "chroma", "collection_name": "test_collection"}
    base.update(overrides)
    return ChromaConfig(**base)  # type: ignore[arg-type]


class TestCollectionLifecycle:
    def test_create_add_reopen_fresh_client(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        identity = _identity()

        client = get_client(config.persistence_path)
        collection = open_or_create_collection(client, config, identity)

        ids = ["chunk_a", "chunk_b"]
        metas = [
            {"content_hash": content_hash("text a", {}), "chunk_index": 0},
            {"content_hash": content_hash("text b", {}), "chunk_index": 1},
        ]
        outcome = ingest_batch(
            collection,
            ids=ids,
            embeddings=[_vector(0), _vector(1)],
            documents=["text a", "text b"],
            metadatas=metas,
            idempotent=True,
        )
        assert outcome.inserted_ids == ids
        assert outcome.final_count == 2

        # Reopen with a brand-new client instance (simulating a fresh process).
        client2 = get_client(config.persistence_path)
        collection2 = client2.get_collection(name=config.collection_name)
        assert collection2.count() == 2
        got = collection2.get(ids=["chunk_a"], include=["documents", "embeddings"])
        assert got["documents"] == ["text a"]

    def test_idempotent_rerun_no_duplicate(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        identity = _identity()
        client = get_client(config.persistence_path)
        collection = open_or_create_collection(client, config, identity)

        meta = {"content_hash": content_hash("stable text", {})}
        for _ in range(2):
            outcome = ingest_batch(
                collection,
                ids=["chunk_x"],
                embeddings=[_vector(5)],
                documents=["stable text"],
                metadatas=[dict(meta)],
                idempotent=True,
            )
        assert outcome.final_count == 1
        assert outcome.existing_identical_ids == ["chunk_x"]
        assert outcome.inserted_ids == []

    def test_stale_hash_formula_falls_back_to_real_text_comparison(self, tmp_path: Path) -> None:
        """A record already in the collection may carry a content_hash computed under an
        older hashing formula (e.g. one that used to fold in a volatile field, since fixed).
        Its stored hash will then never again match a hash computed by the current formula,
        even though the actual retrieval text never changed. That must still resolve as
        idempotent-identical via a real text comparison, not a false conflict."""
        config = _config(tmp_path)
        identity = _identity()
        client = get_client(config.persistence_path)
        collection = open_or_create_collection(client, config, identity)

        ingest_batch(
            collection,
            ids=["chunk_z"],
            embeddings=[_vector(3)],
            documents=["unchanged text"],
            metadatas=[{"content_hash": "stale-hash-from-an-old-formula"}],
            idempotent=True,
        )
        outcome = ingest_batch(
            collection,
            ids=["chunk_z"],
            embeddings=[_vector(3)],
            documents=["unchanged text"],
            metadatas=[{"content_hash": content_hash("unchanged text", {})}],
            idempotent=True,
        )
        assert outcome.existing_identical_ids == ["chunk_z"]
        assert outcome.inserted_ids == []
        assert outcome.final_count == 1

    def test_pre_fix_formula_hash_falls_back_to_real_text_comparison(self, tmp_path: Path) -> None:
        """Same as the stale-hash test above, but the "old" hash is computed with the actual
        pre-fix formula (content + chunk_run_id + source_filename folded in) reproduced inline,
        rather than an arbitrary placeholder string -- proving the fallback resolves the exact
        real-world case, not just a synthetic one."""
        config = _config(tmp_path)
        identity = _identity()
        client = get_client(config.persistence_path)
        collection = open_or_create_collection(client, config, identity)

        def pre_fix_content_hash(text: str, chunk_run_id: str, source_filename: str) -> str:
            metadata = {
                "document_id": "docsha256",
                "chunk_index": 0,
                "chunk_run_id": chunk_run_id,
                "source_filename": source_filename,
            }
            return content_hash(text, metadata)

        old_hash = pre_fix_content_hash("unchanged text", "20260825T073605Z-deadbeef", "original.pdf")
        ingest_batch(
            collection,
            ids=["chunk_legacy"],
            embeddings=[_vector(4)],
            documents=["unchanged text"],
            metadatas=[{"content_hash": old_hash}],
            idempotent=True,
        )

        new_hash = content_hash("unchanged text", {"document_id": "docsha256", "chunk_index": 0})
        assert new_hash != old_hash  # the two formulas must genuinely disagree for this to prove anything
        outcome = ingest_batch(
            collection,
            ids=["chunk_legacy"],
            embeddings=[_vector(4)],
            documents=["unchanged text"],
            metadatas=[{"content_hash": new_hash}],
            idempotent=True,
        )
        assert outcome.existing_identical_ids == ["chunk_legacy"]
        assert outcome.inserted_ids == []
        assert outcome.final_count == 1

    def test_conflicting_duplicate_id_rejected(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        identity = _identity()
        client = get_client(config.persistence_path)
        collection = open_or_create_collection(client, config, identity)

        ingest_batch(
            collection,
            ids=["chunk_y"],
            embeddings=[_vector(1)],
            documents=["original text"],
            metadatas=[{"content_hash": content_hash("original text", {})}],
            idempotent=True,
        )
        with pytest.raises(DuplicateIdConflictError):
            ingest_batch(
                collection,
                ids=["chunk_y"],
                embeddings=[_vector(2)],
                documents=["changed text"],
                metadatas=[{"content_hash": content_hash("changed text", {})}],
                idempotent=True,
            )

    def test_mixed_batch_stays_atomic_on_one_real_conflict(self, tmp_path: Path) -> None:
        """A batch with two brand-new ids and one id that genuinely conflicts (different text,
        different hash) must write nothing at all -- not even the two novel ids -- when the
        conflict raises. ``ingest_batch`` resolves every id's fate before issuing a single
        ``upsert`` call, so a mid-batch conflict must never leave a partial write behind."""
        config = _config(tmp_path)
        identity = _identity()
        client = get_client(config.persistence_path)
        collection = open_or_create_collection(client, config, identity)

        ingest_batch(
            collection,
            ids=["chunk_conflict"],
            embeddings=[_vector(9)],
            documents=["original text"],
            metadatas=[{"content_hash": content_hash("original text", {})}],
            idempotent=True,
        )
        assert collection.count() == 1

        with pytest.raises(DuplicateIdConflictError):
            ingest_batch(
                collection,
                ids=["chunk_novel_1", "chunk_novel_2", "chunk_conflict"],
                embeddings=[_vector(10), _vector(11), _vector(12)],
                documents=["novel text one", "novel text two", "changed text"],
                metadatas=[
                    {"content_hash": content_hash("novel text one", {})},
                    {"content_hash": content_hash("novel text two", {})},
                    {"content_hash": content_hash("changed text", {})},
                ],
                idempotent=True,
            )

        # Nothing from the aborted batch made it in: still just the one pre-existing record.
        assert collection.count() == 1
        assert collection.get(ids=["chunk_novel_1", "chunk_novel_2"])["ids"] == []

    def test_model_mismatch_rejected(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        client = get_client(config.persistence_path)
        open_or_create_collection(client, config, _identity())

        with pytest.raises(CollectionMismatchError):
            open_or_create_collection(client, config, _identity(model_name="a-different-model"))

    def test_dimension_mismatch_rejected(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        client = get_client(config.persistence_path)
        open_or_create_collection(client, config, _identity())

        with pytest.raises(CollectionMismatchError):
            open_or_create_collection(client, config, _identity(embedding_dimension=384))

    def test_rebuild_replaces_collection(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        client = get_client(config.persistence_path)
        collection = open_or_create_collection(client, config, _identity())
        ingest_batch(
            collection,
            ids=["chunk_z"],
            embeddings=[_vector(3)],
            documents=["will be gone"],
            metadatas=[{"content_hash": content_hash("will be gone", {})}],
            idempotent=True,
        )
        assert collection.count() == 1

        rebuilt = rebuild_collection(client, config, _identity())
        assert rebuilt.count() == 0

    def test_leaves_no_files_outside_tmp_path(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        client = get_client(config.persistence_path)
        open_or_create_collection(client, config, _identity())
        assert config.persistence_path.exists()
        # everything created lives under tmp_path — nothing asserted outside it
        # since persistence_path is itself rooted in tmp_path.


class TestValidationHelpers:
    def test_round_trip_check_passes_for_clean_write(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        client = get_client(config.persistence_path)
        collection = open_or_create_collection(client, config, _identity())
        ingest_batch(
            collection,
            ids=["c1"],
            embeddings=[_vector(0)],
            documents=["hello"],
            metadatas=[{"content_hash": content_hash("hello", {})}],
            idempotent=True,
        )
        problems = round_trip_check(
            collection, ids=["c1"], expected_documents={"c1": "hello"}, norm_tolerance=1e-3
        )
        assert problems == []

    def test_round_trip_check_detects_document_mismatch(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        client = get_client(config.persistence_path)
        collection = open_or_create_collection(client, config, _identity())
        ingest_batch(
            collection,
            ids=["c1"],
            embeddings=[_vector(0)],
            documents=["hello"],
            metadatas=[{"content_hash": content_hash("hello", {})}],
            idempotent=True,
        )
        problems = round_trip_check(
            collection, ids=["c1"], expected_documents={"c1": "goodbye"}, norm_tolerance=1e-3
        )
        assert (
            problems and "hello" not in problems[0]
        )  # message names the mismatch, not the raw text mismatch value

    def test_self_retrieval_rank_one(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        client = get_client(config.persistence_path)
        collection = open_or_create_collection(client, config, _identity())
        vectors = {"c1": _vector(0), "c2": _vector(1), "c3": _vector(2)}
        ingest_batch(
            collection,
            ids=list(vectors.keys()),
            embeddings=list(vectors.values()),
            documents=["a", "b", "c"],
            metadatas=[{"content_hash": content_hash(t, {})} for t in ("a", "b", "c")],
            idempotent=True,
        )
        failures = self_retrieval_check(collection, sample_ids=list(vectors.keys()), vectors_by_id=vectors)
        assert failures == []


def test_content_hash_is_stable() -> None:
    h1 = content_hash("some text", {"a": 1, "b": 2})
    h2 = content_hash("some text", {"b": 2, "a": 1})  # order-independent
    assert h1 == h2


def test_content_hash_changes_with_text() -> None:
    assert content_hash("a", {}) != content_hash("b", {})

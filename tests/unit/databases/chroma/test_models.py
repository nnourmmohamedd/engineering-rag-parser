"""CollectionIdentity compatibility-check tests."""

from __future__ import annotations

from engineering_rag.databases.chroma.models import CollectionIdentity


def _identity(**overrides: object) -> CollectionIdentity:
    base = {
        "model_name": "BAAI/bge-base-en-v1.5",
        "embedding_dimension": 768,
        "distance_metric": "cosine",
        "tokenizer_name": "BAAI/bge-base-en-v1.5",
    }
    base.update(overrides)
    return CollectionIdentity(**base)  # type: ignore[arg-type]


class TestCollectionIdentity:
    def test_as_chroma_metadata_includes_hnsw_space(self) -> None:
        meta = _identity().as_chroma_metadata()
        assert meta["hnsw:space"] == "cosine"
        assert meta["model_name"] == "BAAI/bge-base-en-v1.5"

    def test_no_mismatch_against_own_metadata(self) -> None:
        identity = _identity()
        assert identity.mismatches(identity.as_chroma_metadata()) == []

    def test_model_name_mismatch_detected(self) -> None:
        identity = _identity()
        other = _identity(model_name="a-different-model").as_chroma_metadata()
        problems = identity.mismatches(other)
        assert any("model_name" in p for p in problems)

    def test_dimension_mismatch_detected(self) -> None:
        identity = _identity()
        other = _identity(embedding_dimension=384).as_chroma_metadata()
        problems = identity.mismatches(other)
        assert any("embedding_dimension" in p for p in problems)

    def test_missing_fields_in_stored_metadata_detected(self) -> None:
        identity = _identity()
        assert identity.mismatches({}) != []

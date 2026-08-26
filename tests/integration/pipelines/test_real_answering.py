"""Real-acceptance grounded-answering tests: the actual local Ollama server
running the model pinned in ``configs/answering_production.yaml`` (currently
``qwen3:4b`` -- see ``docs/answering/OLLAMA_SETUP.md`` for the model-selection
history), queried against the real, already-built ``engineering_documents_v1``
Chroma collection (122 chunks).

Marked ``slow`` -- runs real model inference, excluded from
``pytest -m "not slow"`` CI. Self-skips if the real collection is not present
or if a local Ollama server with the configured model installed is not
reachable (see ``requires_ollama`` in ``tests/conftest.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_rag.pipelines.answering_config import load_answering_config
from engineering_rag.pipelines.answering_pipeline import run_ask_pipeline, validate_all
from engineering_rag.pipelines.retrieval_config import load_retrieval_config
from tests.conftest import requires_ollama

pytestmark = pytest.mark.slow

_ANSWERING_PROFILE = Path("configs/answering_production.yaml")
_RETRIEVAL_PROFILE = Path("configs/retrieval_production.yaml")


def _collection_available() -> bool:
    config = load_retrieval_config(_RETRIEVAL_PROFILE)
    persistence_path = Path(config.chroma.persistence_path)
    return persistence_path.is_dir() and any(persistence_path.iterdir())


requires_real_collection = pytest.mark.skipif(
    not _collection_available(),
    reason="data/output/databases/chroma not present (run engrag-index build first)",
)


@requires_ollama
@requires_real_collection
class TestRealGroundedAnswering:
    def test_ollama_health_and_model_installed(self) -> None:
        answering_config = load_answering_config(_ANSWERING_PROFILE)
        retrieval_config = load_retrieval_config(_RETRIEVAL_PROFILE)
        report = validate_all(answering_config, retrieval_config)
        assert report.ollama.checks[0]["passed"] is True

    def test_real_answerable_question_produces_grounded_answer(self) -> None:
        answering_config = load_answering_config(_ANSWERING_PROFILE)
        retrieval_config = load_retrieval_config(_RETRIEVAL_PROFILE)
        _rr, context, answer, trace, run_dir = run_ask_pipeline(
            "What activities are performed during the FEED phase?",
            answering_config,
            retrieval_config,
            retrieval_mode="vector",
        )
        assert answer.status in ("answered", "insufficient_evidence")
        assert answer.model_tag == answering_config.ollama.model
        assert answer.model_digest is not None
        # No hidden chain-of-thought is ever captured: the model runs with think=false, so the
        # raw content is exactly the structured JSON answer, never a separate reasoning field.
        assert trace.raw_model_content is not None
        assert "<think>" not in trace.raw_model_content
        assert run_dir is not None
        for name in ("query.json", "context.json", "answer.json", "grounding_report.json", "manifest.json"):
            assert (run_dir.root / name).is_file()

    def test_real_out_of_domain_question_refuses(self) -> None:
        answering_config = load_answering_config(_ANSWERING_PROFILE)
        retrieval_config = load_retrieval_config(_RETRIEVAL_PROFILE)
        _rr, _ctx, answer, _trace, _run_dir = run_ask_pipeline(
            "Who won the FIFA World Cup in 2030?",
            answering_config,
            retrieval_config,
            retrieval_mode="vector",
        )
        assert answer.status == "insufficient_evidence"

    @pytest.mark.parametrize("mode", ["vector", "hybrid", "vector-rerank", "hybrid-rerank"])
    def test_real_query_in_every_retrieval_mode(self, mode: str) -> None:
        answering_config = load_answering_config(_ANSWERING_PROFILE)
        retrieval_config = load_retrieval_config(_RETRIEVAL_PROFILE)
        if mode in ("hybrid", "hybrid-rerank"):
            index_path = Path(retrieval_config.bm25.index_path)
            if not (index_path / "bm25_manifest.json").is_file():
                pytest.skip("BM25 index not built; run `engrag-retrieve build-bm25` first")

        _rr, _ctx, answer, _trace, _run_dir = run_ask_pipeline(
            "What is an instrument index?",
            answering_config,
            retrieval_config,
            retrieval_mode=mode,
        )
        assert answer.retrieval_mode == mode
        assert answer.status in ("answered", "insufficient_evidence", "validation_failed")

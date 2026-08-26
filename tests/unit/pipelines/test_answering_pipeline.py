from __future__ import annotations

from pathlib import Path

from engineering_rag.pipelines.answering_config import AnsweringPipelineConfig
from engineering_rag.pipelines.answering_pipeline import (
    ChromaNeighborProvider,
    validate_all,
    validate_ollama_environment,
)
from engineering_rag.pipelines.retrieval_config import RetrievalConfig
from tests.support.fake_llm_client import FakeLLMClient


def _config(**ollama_overrides: object) -> AnsweringPipelineConfig:
    return AnsweringPipelineConfig(ollama=dict(model="qwen3:8b", **ollama_overrides))  # type: ignore[arg-type]


class _FakeChromaCollection:
    def __init__(self, records: dict[str, dict[str, object]]) -> None:
        self._records = records

    def get(self, *, ids: list[str], include: list[str]) -> dict[str, list[object]]:
        record = self._records.get(ids[0])
        if record is None:
            return {"ids": [], "documents": [], "metadatas": []}
        return {"ids": [ids[0]], "documents": [record["text"]], "metadatas": [record["meta"]]}


class TestChromaNeighborProvider:
    def test_get_chunk_found(self) -> None:
        collection = _FakeChromaCollection(
            {
                "c1": {
                    "text": "neighbor text",
                    "meta": {
                        "document_id": "d1",
                        "source_filename": "doc.pdf",
                        "page_numbers": [1, 2],
                        "heading_path": ["A", "B"],
                        "section_title": "Sec",
                        "content_type": "text",
                        "content_hash": "h1",
                        "previous_chunk_id": "c0",
                        "next_chunk_id": "c2",
                    },
                }
            }
        )
        provider = ChromaNeighborProvider(collection)
        chunk = provider.get_chunk("c1")
        assert chunk is not None
        assert chunk.retrieval_text == "neighbor text"
        assert chunk.document_id == "d1"
        assert chunk.page_numbers == [1, 2]
        assert chunk.previous_chunk_id == "c0"
        assert chunk.next_chunk_id == "c2"

    def test_get_chunk_not_found_returns_none(self) -> None:
        provider = ChromaNeighborProvider(_FakeChromaCollection({}))
        assert provider.get_chunk("missing") is None


class TestValidateOllamaEnvironment:
    def test_unreachable_server_reports_fail_and_stops(self) -> None:
        client = FakeLLMClient(healthy=False)
        report = validate_ollama_environment(_config(), llm_client=client)
        assert report.passed is False
        assert report.checks[0]["check_id"] == "ollama_reachable"
        assert len(report.checks) == 1  # never proceeds to version/model checks once unreachable

    def test_reachable_with_matching_digest_passes(self) -> None:
        client = FakeLLMClient(healthy=True, digest="abc123")
        report = validate_ollama_environment(
            _config(expected_digest="abc123", strict_digest=True), llm_client=client
        )
        assert report.passed is True
        by_id = {c["check_id"]: c for c in report.checks}
        assert by_id["model_digest_matches"]["passed"] is True

    def test_digest_mismatch_fails_when_strict(self) -> None:
        client = FakeLLMClient(healthy=True, digest="observed-digest")
        report = validate_ollama_environment(
            _config(expected_digest="different-digest", strict_digest=True), llm_client=client
        )
        assert report.passed is False
        by_id = {c["check_id"]: c for c in report.checks}
        assert by_id["model_digest_matches"]["passed"] is False

    def test_digest_check_skipped_when_expected_digest_unset(self) -> None:
        client = FakeLLMClient(healthy=True, digest="whatever")
        report = validate_ollama_environment(_config(expected_digest=None), llm_client=client)
        by_id = {c["check_id"]: c for c in report.checks}
        assert by_id["model_digest_matches"]["passed"] is True

    def test_model_not_installed_fails(self) -> None:
        client = FakeLLMClient(healthy=True, installed_models=[])
        report = validate_ollama_environment(_config(), llm_client=client)
        assert report.passed is False
        by_id = {c["check_id"]: c for c in report.checks}
        assert by_id["model_installed"]["passed"] is False

    def test_validate_never_calls_generate(self) -> None:
        client = FakeLLMClient(healthy=True)
        validate_ollama_environment(_config(), llm_client=client)
        assert client.calls == []  # /api/chat is never invoked by validate


class TestValidateAll:
    def test_missing_chroma_path_reported_without_crashing(self, tmp_path: Path) -> None:
        answering_config = _config()
        retrieval_config = RetrievalConfig(chroma={"persistence_path": tmp_path / "no-such-chroma"})
        client = FakeLLMClient(healthy=False)
        report = validate_all(answering_config, retrieval_config, llm_client=client)
        assert report.passed is False
        assert report.retrieval.checks[0]["check_id"] == "chroma_path_exists"
        assert report.retrieval.checks[0]["passed"] is False

    def test_config_checks_include_budget_and_prompt_contract(self, tmp_path: Path) -> None:
        answering_config = _config()
        retrieval_config = RetrievalConfig(chroma={"persistence_path": tmp_path / "no-such-chroma"})
        client = FakeLLMClient(healthy=False)
        report = validate_all(answering_config, retrieval_config, llm_client=client)
        ids = {c["check_id"] for c in report.config_checks}
        assert "token_budget_fits_context_window" in ids
        assert "prompt_contract_resolves" in ids

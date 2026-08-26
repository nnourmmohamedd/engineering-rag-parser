from __future__ import annotations

from engineering_rag.clients.ollama.errors import OllamaConnectionError
from engineering_rag.services.answerer import AnsweringConfig, GroundedAnswerService
from engineering_rag.services.context_builder.models import ContextPackage, SelectedSource
from engineering_rag.services.grounding import GroundingConfig
from tests.support.fake_llm_client import FakeLLMClient, ScriptedResponse, make_answer_payload, scripted_json


def _source(citation_id: str = "S1", text: str = "FEED develops the control philosophy.") -> SelectedSource:
    return SelectedSource(
        citation_id=citation_id,
        chunk_id="c1",
        document_id="d1",
        retrieval_text=text,
        selection_order=1,
        token_count=10,
    )


def _package(*sources: SelectedSource, warnings: list[str] | None = None) -> ContextPackage:
    return ContextPackage(
        query="What does FEED develop?",
        query_hash="h",
        retrieval_mode="vector",
        selected_sources=list(sources),
        context_token_count=10,
        token_budget=5000,
        reserved_output_tokens=1024,
        prompt_overhead_tokens=1300,
        context_text='<SOURCE id="S1">FEED develops the control philosophy.</SOURCE>',
        warnings=warnings or [],
    )


def _service(llm_client: FakeLLMClient, *, allow_single_repair: bool = True) -> GroundedAnswerService:
    return GroundedAnswerService(
        llm_client=llm_client,
        answering_config=AnsweringConfig(allow_single_repair=allow_single_repair),
        grounding_config=GroundingConfig(),
        model_tag="qwen3:8b",
        model_digest="abc123",
        generation_config={"temperature": 0.0},
    )


class TestSuccessfulAnswer:
    def test_grounded_answer_returns_answered_status(self) -> None:
        payload = make_answer_payload(
            answer="FEED develops the control philosophy [S1].",
            citations_used=["S1"],
            supporting_evidence=[
                {"citation_id": "S1", "supporting_quote": "FEED develops the control philosophy"}
            ],
        )
        client = FakeLLMClient(responses=[scripted_json(payload)])
        response, trace = _service(client).answer("What does FEED develop?", _package(_source()))

        assert response.status == "answered"
        assert response.validation.status == "PASS"
        assert response.citations[0].citation_id == "S1"
        assert trace.raw_model_content is not None
        assert trace.parsed_draft is not None


class TestPreGenerationRefusal:
    def test_empty_context_refuses_without_calling_llm(self) -> None:
        client = FakeLLMClient(responses=[])
        response, trace = _service(client).answer("unanswerable question", _package())

        assert response.status == "insufficient_evidence"
        assert response.insufficient_evidence is True
        assert client.calls == []
        assert trace.raw_model_content is None


class TestModelDeclaredInsufficientEvidence:
    def test_insufficient_evidence_from_model(self) -> None:
        payload = make_answer_payload(
            answer="The evidence does not cover this.",
            insufficient_evidence=True,
            insufficiency_reason="No relevant chunk found.",
        )
        client = FakeLLMClient(responses=[scripted_json(payload)])
        response, _trace = _service(client).answer("q", _package(_source()))
        assert response.status == "insufficient_evidence"
        assert response.insufficiency_reason == "No relevant chunk found."


class TestUnknownAndMissingCitations:
    def test_unknown_citation_fails_validation_then_repairs_successfully(self) -> None:
        bad_payload = make_answer_payload(answer="Claim [S1][S2].", citations_used=["S1", "S2"])
        good_payload = make_answer_payload(
            answer="Claim [S1].",
            citations_used=["S1"],
            supporting_evidence=[
                {"citation_id": "S1", "supporting_quote": "FEED develops the control philosophy"}
            ],
        )
        client = FakeLLMClient(responses=[scripted_json(bad_payload), scripted_json(good_payload)])
        response, _trace = _service(client).answer("q", _package(_source()))

        assert response.repair_attempted is True
        assert response.status == "answered"
        assert len(client.calls) == 2

    def test_unknown_citation_fails_validation_repair_disabled(self) -> None:
        bad_payload = make_answer_payload(answer="Claim [S2].", citations_used=["S2"])
        client = FakeLLMClient(responses=[scripted_json(bad_payload)])
        response, _trace = _service(client, allow_single_repair=False).answer("q", _package(_source()))

        assert response.status == "validation_failed"
        assert response.repair_attempted is False
        assert len(client.calls) == 1

    def test_missing_citation_on_non_refusal_fails(self) -> None:
        payload = make_answer_payload(answer="An answer with no citation markers at all.", citations_used=[])
        client = FakeLLMClient(responses=[scripted_json(payload)])
        response, _trace = _service(client, allow_single_repair=False).answer("q", _package(_source()))
        assert response.status == "validation_failed"

    def test_repair_attempt_that_also_fails_still_reports_validation_failed(self) -> None:
        bad1 = make_answer_payload(answer="Claim [S9].", citations_used=["S9"])
        bad2 = make_answer_payload(answer="Still claim [S9].", citations_used=["S9"])
        client = FakeLLMClient(responses=[scripted_json(bad1), scripted_json(bad2)])
        response, _trace = _service(client).answer("q", _package(_source()))
        assert response.status == "validation_failed"
        assert response.repair_attempted is True


class TestSupportingQuoteMatch:
    def test_exact_and_mismatched_quotes(self) -> None:
        good = make_answer_payload(
            answer="Claim [S1].",
            citations_used=["S1"],
            supporting_evidence=[
                {"citation_id": "S1", "supporting_quote": "FEED develops the control philosophy"}
            ],
        )
        client = FakeLLMClient(responses=[scripted_json(good)])
        response, _trace = _service(client).answer("q", _package(_source()))
        assert response.validation.status == "PASS"

        bad = make_answer_payload(
            answer="Claim [S1].",
            citations_used=["S1"],
            supporting_evidence=[{"citation_id": "S1", "supporting_quote": "totally fabricated text"}],
        )
        client2 = FakeLLMClient(responses=[scripted_json(bad)])
        response2, _trace2 = _service(client2, allow_single_repair=False).answer("q", _package(_source()))
        assert response2.status == "validation_failed"


class TestMalformedOutput:
    def test_malformed_json_triggers_repair_then_succeeds(self) -> None:
        good = make_answer_payload(
            answer="Claim [S1].",
            citations_used=["S1"],
            supporting_evidence=[
                {"citation_id": "S1", "supporting_quote": "FEED develops the control philosophy"}
            ],
        )
        client = FakeLLMClient(
            responses=[ScriptedResponse(raw_content="not json at all"), scripted_json(good)]
        )
        response, _trace = _service(client).answer("q", _package(_source()))
        assert response.repair_attempted is True
        assert response.status == "answered"

    def test_malformed_json_after_repair_exhausted_is_generation_failed(self) -> None:
        client = FakeLLMClient(
            responses=[ScriptedResponse(raw_content="bad"), ScriptedResponse(raw_content="still bad")]
        )
        response, trace = _service(client).answer("q", _package(_source()))
        assert response.status == "generation_failed"
        assert response.repair_attempted is True
        assert trace.parsed_draft is None

    def test_repair_never_spent_on_connection_failure(self) -> None:
        client = FakeLLMClient(responses=[ScriptedResponse(raises=OllamaConnectionError("refused"))])
        response, _trace = _service(client).answer("q", _package(_source()))
        assert response.status == "generation_failed"
        assert response.repair_attempted is False  # infrastructure failure is never repaired
        assert len(client.calls) == 1


class TestDeterministicFakeAndProvenance:
    def test_citation_summary_preserves_provenance(self) -> None:
        source = SelectedSource(
            citation_id="S1",
            chunk_id="chunk-42",
            document_id="doc1",
            retrieval_text="FEED develops the control philosophy.",
            source_filename="Instrumentation.pdf",
            page_numbers=[3, 4],
            section_title="Section 2",
            content_hash="hash123",
            selection_order=1,
            token_count=10,
            similarity_score=0.9,
        )
        payload = make_answer_payload(
            answer="Claim [S1].",
            citations_used=["S1"],
            supporting_evidence=[
                {"citation_id": "S1", "supporting_quote": "FEED develops the control philosophy"}
            ],
        )
        client = FakeLLMClient(responses=[scripted_json(payload)])
        response, _trace = _service(client).answer("q", _package(source))

        citation = response.citations[0]
        assert citation.chunk_id == "chunk-42"
        assert citation.source_filename == "Instrumentation.pdf"
        assert citation.page_numbers == [3, 4]
        assert citation.section_title == "Section 2"
        assert citation.similarity_score == 0.9

    def test_correct_status_selection_matrix(self) -> None:
        cases = [
            (
                make_answer_payload(
                    answer="ok [S1].",
                    citations_used=["S1"],
                    supporting_evidence=[
                        {"citation_id": "S1", "supporting_quote": "FEED develops the control philosophy"}
                    ],
                ),
                "answered",
            ),
            (make_answer_payload(answer="no evidence", insufficient_evidence=True), "insufficient_evidence"),
        ]
        for payload, expected_status in cases:
            client = FakeLLMClient(responses=[scripted_json(payload)])
            response, _trace = _service(client).answer("q", _package(_source()))
            assert response.status == expected_status

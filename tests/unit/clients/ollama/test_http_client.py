"""Fast, network-free tests for :class:`OllamaHTTPClient` using a mocked ``httpx`` transport."""

from __future__ import annotations

import json

import httpx
import pytest

from engineering_rag.clients.ollama.config import OllamaConfig
from engineering_rag.clients.ollama.errors import (
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaResponseError,
    OllamaTimeoutError,
)
from engineering_rag.clients.ollama.http_client import OllamaHTTPClient


def _client(handler, **config_overrides: object) -> OllamaHTTPClient:
    config = OllamaConfig(**config_overrides)  # type: ignore[arg-type]
    client = OllamaHTTPClient(config)
    client._client = httpx.Client(transport=httpx.MockTransport(handler), base_url=config.base_url)
    return client


class TestConfigConstructionNeverHitsNetwork:
    def test_construction_makes_no_request(self) -> None:
        # If this made a real request it would raise/hang against a closed port; it must not.
        OllamaHTTPClient(OllamaConfig())

    def test_think_must_be_false(self) -> None:
        with pytest.raises(ValueError, match="think"):
            OllamaConfig(think=True)

    def test_base_url_must_be_localhost(self) -> None:
        with pytest.raises(ValueError, match="local"):
            OllamaConfig(base_url="http://example.com:11434")


class TestHealthCheck:
    def test_success(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"version": "0.5.0"})

        assert _client(handler, max_retries=0).health_check() is True

    def test_server_unreachable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        assert _client(handler, max_retries=0).health_check() is False


class TestVersion:
    def test_parses_version_string(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"version": "0.9.1"})

        assert _client(handler, max_retries=0).version().version == "0.9.1"

    def test_non_200_raises_response_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        with pytest.raises(OllamaResponseError):
            _client(handler, max_retries=0).version()

    def test_malformed_json_raises_response_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not json")

        with pytest.raises(OllamaResponseError):
            _client(handler, max_retries=0).version()


class TestModelInfoAndDigest:
    def test_installed_model_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "qwen3:8b",
                            "digest": "abc123",
                            "size": 5_000_000_000,
                            "details": {
                                "parameter_size": "8.2B",
                                "quantization_level": "Q4_K_M",
                                "family": "qwen3",
                            },
                        }
                    ]
                },
            )

        info = _client(handler, max_retries=0).model_info("qwen3:8b")
        assert info.digest == "abc123"
        assert info.parameter_size == "8.2B"
        assert info.quantization_level == "Q4_K_M"

    def test_missing_model_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"models": []})

        with pytest.raises(OllamaModelNotFoundError):
            _client(handler, max_retries=0).model_info("qwen3:8b")


class TestTimeoutAndRetry:
    def test_timeout_raises_immediately_no_retry(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            raise httpx.ReadTimeout("slow")

        with pytest.raises(OllamaTimeoutError):
            _client(handler, max_retries=2).version()
        assert calls["n"] == 1  # never retried

    def test_transient_connection_error_is_retried_then_succeeds(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectError("refused")
            return httpx.Response(200, json={"version": "1.0.0"})

        result = _client(handler, max_retries=1).version()
        assert result.version == "1.0.0"
        assert calls["n"] == 2

    def test_retry_bounded_then_raises(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            raise httpx.ConnectError("refused")

        with pytest.raises(OllamaConnectionError):
            _client(handler, max_retries=1).version()
        assert calls["n"] == 2  # 1 initial + 1 retry, then gives up

    def test_bad_schema_response_is_never_retried(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(500, text="server error")

        with pytest.raises(OllamaResponseError):
            _client(handler, max_retries=3).version()
        assert calls["n"] == 1


class TestGenerateStructured:
    def test_sends_think_false_and_options(self) -> None:
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "model": "qwen3:8b",
                    "message": {"role": "assistant", "content": '{"answer": "hi"}'},
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 42,
                    "eval_count": 7,
                    "load_duration": 1000,
                    "prompt_eval_duration": 2000,
                    "eval_duration": 3000,
                    "total_duration": 6000,
                },
            )

        client = _client(
            handler,
            max_retries=0,
            temperature=0.0,
            seed=42,
            context_window_tokens=8192,
            max_output_tokens=1024,
        )
        result = client.generate_structured(
            system_prompt="sys", user_prompt="usr", json_schema={"type": "object"}
        )

        assert captured["body"]["think"] is False
        assert captured["body"]["stream"] is False
        assert captured["body"]["options"]["num_ctx"] == 8192
        assert captured["body"]["options"]["num_predict"] == 1024
        assert captured["body"]["options"]["seed"] == 42
        assert captured["body"]["format"] == {"type": "object"}

        assert result.raw_content == '{"answer": "hi"}'
        assert result.metrics.prompt_eval_count == 42
        assert result.metrics.eval_count == 7
        assert result.metrics.total_duration_s == pytest.approx(6000 / 1e9)
        assert result.done is True
        assert result.done_reason == "stop"

    def test_model_not_found_status_maps_to_typed_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="not found")

        with pytest.raises(OllamaModelNotFoundError):
            _client(handler, max_retries=0).generate_structured(
                system_prompt="s", user_prompt="u", json_schema={}
            )

    def test_malformed_json_content_is_returned_raw_for_caller_to_handle(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"model": "qwen3:8b", "message": {"content": "not-json"}, "done": True},
            )

        result = _client(handler, max_retries=0).generate_structured(
            system_prompt="s", user_prompt="u", json_schema={}
        )
        assert result.raw_content == "not-json"  # parsing is the answerer's job, not the transport's

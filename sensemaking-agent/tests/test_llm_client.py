from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from sensemaking_agent import llm_client


class _Response:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_generate_text_sync_ollama_success() -> None:
    with patch(
        "sensemaking_agent.llm_client.urllib.request.urlopen",
        return_value=_Response({"response": "ollama output"}),
    ) as mocked:
        result = llm_client.generate_text_sync(
            prompt="hello",
            model="qwen2.5:7b",
            provider="ollama",
            base_url="http://localhost:11434",
        )

    request = mocked.call_args.args[0]
    assert result == "ollama output"
    assert request.full_url == "http://localhost:11434/api/generate"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["prompt"] == "hello"
    assert payload["model"] == "qwen2.5:7b"


def test_generate_text_sync_openai_success() -> None:
    with patch(
        "sensemaking_agent.llm_client.urllib.request.urlopen",
        return_value=_Response(
            {"choices": [{"message": {"content": "openai output"}}]}
        ),
    ) as mocked:
        result = llm_client.generate_text_sync(
            prompt="hello",
            model="gpt-test",
            provider="openai-compatible",
            base_url="https://example.com/v1",
            api_key="secret",
        )

    request = mocked.call_args.args[0]
    assert result == "openai output"
    assert request.full_url == "https://example.com/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer secret"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["messages"][0]["content"] == "hello"
    assert payload["model"] == "gpt-test"


def test_generate_text_sync_openai_empty_choices_returns_empty_string() -> None:
    with patch(
        "sensemaking_agent.llm_client.urllib.request.urlopen",
        return_value=_Response({"choices": []}),
    ):
        result = llm_client.generate_text_sync(
            prompt="hello",
            model="gpt-test",
            provider="openai",
            base_url="https://example.com/v1",
        )

    assert result == ""


def test_generate_text_sync_returns_none_on_transport_failure() -> None:
    with patch(
        "sensemaking_agent.llm_client.urllib.request.urlopen",
        side_effect=OSError("boom"),
    ):
        result = llm_client.generate_text_sync(
            prompt="hello",
            model="qwen2.5:7b",
            provider="ollama",
            base_url="http://localhost:11434",
        )

    assert result is None


@pytest.mark.asyncio
async def test_generate_text_async_uses_executor_path() -> None:
    with patch(
        "sensemaking_agent.llm_client.generate_text_sync",
        return_value="async output",
    ) as mocked:
        result = await llm_client.generate_text(
            prompt="hello",
            model="qwen2.5:7b",
            provider="ollama",
        )

    assert result == "async output"
    mocked.assert_called_once()
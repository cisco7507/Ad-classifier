import sys
import types

import pytest

# `video_service.core.llm` imports `ddgs`; stub it for unit tests.
if "ddgs" not in sys.modules:
    ddgs_stub = types.ModuleType("ddgs")
    ddgs_stub.DDGS = object
    sys.modules["ddgs"] = ddgs_stub

from video_service.core.llm import HybridLLM

pytestmark = pytest.mark.unit


class _DummyResponse:
    def __init__(self, payload: dict, status_code: int = 200, text: str = "") -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self) -> dict:
        return self._payload


def test_query_pipeline_uses_timeout_300_for_remote_calls(monkeypatch):
    calls: list[dict] = []

    def _fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "timeout": timeout})
        if "api/generate" in url:
            return _DummyResponse({"response": '{"brand":"B","category":"C","confidence":0.9,"reasoning":"ok"}'})
        return _DummyResponse({"choices": [{"message": {"content": '{"brand":"B","category":"C","confidence":0.9,"reasoning":"ok"}'}}]})

    llm = HybridLLM()
    monkeypatch.setattr("video_service.core.llm.requests.post", _fake_post)

    llm.query_pipeline(
        provider="Ollama",
        backend_model="qwen3-vl:8b-instruct",
        text="sample",
        categories="Auto",
        enable_search=False,
    )
    llm.query_pipeline(
        provider="LM Studio",
        backend_model="local-model",
        text="sample",
        categories="Auto",
        enable_search=False,
    )

    assert len(calls) == 2
    assert all(call["timeout"] == 300 for call in calls)


def test_query_agent_uses_timeout_300_for_remote_calls(monkeypatch):
    calls: list[dict] = []

    def _fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "timeout": timeout})
        if "api/generate" in url:
            return _DummyResponse({"response": "[TOOL: FINAL | brand=\"Brand\" category=\"Cat\" reason=\"ok\"]"})
        return _DummyResponse({"choices": [{"message": {"content": "[TOOL: FINAL | brand=\"Brand\" category=\"Cat\" reason=\"ok\"]"}}]})

    llm = HybridLLM()
    monkeypatch.setattr("video_service.core.llm.requests.post", _fake_post)

    llm.query_agent(
        provider="Ollama",
        backend_model="qwen3-vl:8b-instruct",
        prompt="prompt",
    )
    llm.query_agent(
        provider="LM Studio",
        backend_model="local-model",
        prompt="prompt",
    )

    assert len(calls) == 2
    assert all(call["timeout"] == 300 for call in calls)

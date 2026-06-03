from __future__ import annotations

import asyncio

import pytest

from services.graphs.server import mcp, run_graph


def test_server_name_uses_graphs_prefix():
    assert mcp.name.startswith("graphs")


def test_tools_list_contains_only_run_graph():
    tools = asyncio.run(mcp.list_tools())
    names = [t.name for t in tools]
    assert names == ["run_graph"]


def test_run_graph_tool_description_mentions_echo():
    tools = asyncio.run(mcp.list_tools())
    assert "echo" in tools[0].description


def test_echo_round_trip():
    result = asyncio.run(run_graph("echo", {"text": "hello"}))
    assert result == "hello"


def test_opinion_with_mock_llm(monkeypatch):
    from services.graphs.library import opinion

    captured = {}

    class _Reply:
        content = "Sound: clear scope. Risk: scope creep. Simplification: drop X. Assumption: Y holds."

    class _FakeLLM:
        async def ainvoke(self, messages):
            for role, content in messages:
                if role == "user":
                    captured["user"] = content
            return _Reply()

    monkeypatch.setattr(opinion, "init_chat_model", lambda **_: _FakeLLM())

    result = asyncio.run(run_graph("opinion", {"proposal": "Build a new microservice for X."}))
    assert "Sound" in result and "Risk" in result
    assert captured["user"] == "Build a new microservice for X."


def test_opinion_propagates_llm_error(monkeypatch):
    from services.graphs.library import opinion

    class _FakeLLM:
        async def ainvoke(self, messages):
            raise RuntimeError("upstream LLM exploded")

    monkeypatch.setattr(opinion, "init_chat_model", lambda **_: _FakeLLM())

    with pytest.raises(RuntimeError, match="upstream LLM exploded"):
        asyncio.run(run_graph("opinion", {"proposal": "anything"}))

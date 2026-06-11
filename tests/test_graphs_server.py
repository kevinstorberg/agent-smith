from __future__ import annotations

import asyncio

import pytest

from services.graphs.runtime import GraphContractError
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


def test_model_factory_uses_aws_kimi_server_config(monkeypatch):
    from services.graphs import model_factory

    captured = {}

    class _FakeTransportAdapter:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setenv("OPINION_MODEL_PROVIDER", "aws_kimi")
    monkeypatch.setenv("OPINION_MODEL_ID", "moonshotai/Kimi-K2.6")
    monkeypatch.setenv("OPINION_MODEL_SERVER_URL", "https://kimi.aws.example/v1")
    monkeypatch.setenv("OPINION_MODEL_SERVER_API_KEY", "test-key")
    monkeypatch.setattr(model_factory, "ChatCompletionsTransportAdapter", _FakeTransportAdapter)

    model = model_factory.build_chat_model("opinion")

    assert isinstance(model, _FakeTransportAdapter)
    assert captured["model"] == "moonshotai/Kimi-K2.6"
    assert captured["base_url"] == "https://kimi.aws.example/v1"
    assert captured["api_key"] == "test-key"
    assert captured["temperature"] == 1.0
    assert captured["top_p"] == 0.95
    assert captured["extra_body"] == {"chat_template_kwargs": {"thinking": True}}


def test_model_factory_grader_role_falls_back_to_opinion_config(monkeypatch):
    from services.graphs.model_factory import load_model_config

    monkeypatch.setenv("OPINION_MODEL_PROVIDER", "aws_kimi")
    monkeypatch.setenv("OPINION_MODEL_ID", "moonshotai/Kimi-K2.6")
    monkeypatch.setenv("OPINION_MODEL_SERVER_URL", "https://kimi.aws.example/v1")
    monkeypatch.setenv("OPINION_MODEL_SERVER_API_KEY", "test-key")

    config = load_model_config("opinion_grader", fallback_role="opinion")

    assert config.provider == "aws_kimi"
    assert config.model_id == "moonshotai/Kimi-K2.6"
    assert config.server_url == "https://kimi.aws.example/v1"
    assert config.server_api_key == "test-key"


def test_opinion_with_mock_deep_agent(monkeypatch):
    from services.graphs.library import opinion

    captured = {}

    class _Reply:
        content = "Sound: clear scope. Risk: scope creep. Simplification: drop X. Assumption: Y holds."

    class _FakeAgent:
        async def ainvoke(self, payload, config=None):
            captured["payload"] = payload
            captured["config"] = config
            return {
                "messages": [_Reply()],
                "_rubric_status": "satisfied",
                "_rubric_evaluations": [
                    {"result": "satisfied", "explanation": "All criteria pass."}
                ],
            }

    monkeypatch.setattr(
        opinion,
        "_load_selected_rules",
        lambda: [
            ("DRY", "## DRY\n* **Your Process:**\n    1. Search existing code."),
        ],
    )
    monkeypatch.setattr(
        opinion,
        "create_rubric_agent",
        lambda **_: _FakeAgent(),
    )

    result = asyncio.run(run_graph("opinion", {"proposal": "Build a new microservice for X."}))

    assert "Sound" in result and "Risk" in result
    assert captured["payload"]["messages"][0].content == "Build a new microservice for X."
    assert "- DRY: Search existing code" in captured["payload"]["rubric"]
    assert captured["config"]["configurable"]["thread_id"].startswith("opinion-")


@pytest.mark.parametrize("status", ["max_iterations_reached", "failed", "grader_error"])
def test_opinion_raises_graph_contract_error_for_terminal_rubric_failures(
    monkeypatch,
    status,
):
    from services.graphs.library import opinion

    class _FakeAgent:
        async def ainvoke(self, payload, config=None):
            return {
                "messages": [],
                "_rubric_status": status,
                "_rubric_evaluations": [
                    {"result": "needs_revision", "explanation": "Needs more rigor."}
                ],
            }

    monkeypatch.setattr(
        opinion,
        "_load_selected_rules",
        lambda: [
            ("DRY", "## DRY\n* **Your Process:**\n    1. Search existing code."),
        ],
    )
    monkeypatch.setattr(
        opinion,
        "create_rubric_agent",
        lambda **_: _FakeAgent(),
    )

    with pytest.raises(GraphContractError, match=status):
        asyncio.run(run_graph("opinion", {"proposal": "anything"}))


def test_opinion_propagates_agent_error(monkeypatch):
    from services.graphs.library import opinion

    class _FakeAgent:
        async def ainvoke(self, payload, config=None):
            raise RuntimeError("upstream LLM exploded")

    monkeypatch.setattr(
        opinion,
        "_load_selected_rules",
        lambda: [
            ("DRY", "## DRY\n* **Your Process:**\n    1. Search existing code."),
        ],
    )
    monkeypatch.setattr(
        opinion,
        "create_rubric_agent",
        lambda **_: _FakeAgent(),
    )

    with pytest.raises(RuntimeError, match="upstream LLM exploded"):
        asyncio.run(run_graph("opinion", {"proposal": "anything"}))

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


_FAKE_BEDROCK_API_KEY = "bedrock-test-key-0123456789abcdef"


def _clear_model_env(monkeypatch):
    suffixes = (
        "MODEL_PROVIDER", "MODEL_ID", "MODEL", "MODEL_SERVER_URL", "MODEL_BASE_URL",
        "MODEL_SERVER_API_KEY", "MODEL_API_KEY", "MODEL_REGION",
        "MODEL_TEMPERATURE", "MODEL_TOP_P", "MODEL_THINKING",
    )
    for prefix in ("OPINION", "OPINION_GRADER", "GRAPH"):
        for suffix in suffixes:
            monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)


def _patch_fake_adapter(monkeypatch):
    from services.graphs import model_factory

    captured = {}

    class _FakeTransportAdapter:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(model_factory, "ChatCompletionsTransportAdapter", _FakeTransportAdapter)
    return captured, _FakeTransportAdapter


def test_model_factory_bedrock_builds_mantle_adapter(monkeypatch):
    from services.graphs import model_factory

    _clear_model_env(monkeypatch)
    captured, fake_cls = _patch_fake_adapter(monkeypatch)
    monkeypatch.setenv("OPINION_MODEL_SERVER_API_KEY", _FAKE_BEDROCK_API_KEY)

    model = model_factory.build_chat_model("opinion")

    assert isinstance(model, fake_cls)
    assert captured["model"] == "moonshotai.kimi-k2.5"
    assert captured["base_url"] == "https://bedrock-mantle.us-east-1.api.aws/v1"
    assert captured["api_key"] == _FAKE_BEDROCK_API_KEY
    assert captured["temperature"] == 1.0
    assert captured["top_p"] == 0.95
    assert "extra_body" not in captured


def test_model_factory_bedrock_derives_url_from_region(monkeypatch):
    from services.graphs import model_factory

    _clear_model_env(monkeypatch)
    captured, _ = _patch_fake_adapter(monkeypatch)
    monkeypatch.setenv("OPINION_MODEL_REGION", "us-west-2")
    monkeypatch.setenv("OPINION_MODEL_SERVER_API_KEY", _FAKE_BEDROCK_API_KEY)

    model_factory.build_chat_model("opinion")

    assert captured["base_url"] == "https://bedrock-mantle.us-west-2.api.aws/v1"


def test_model_factory_bedrock_explicit_url_overrides_region(monkeypatch):
    from services.graphs import model_factory

    _clear_model_env(monkeypatch)
    captured, _ = _patch_fake_adapter(monkeypatch)
    monkeypatch.setenv("OPINION_MODEL_REGION", "us-west-2")
    monkeypatch.setenv("OPINION_MODEL_SERVER_URL", "https://bedrock-mantle.eu-central-1.api.aws/v1")
    monkeypatch.setenv("OPINION_MODEL_SERVER_API_KEY", _FAKE_BEDROCK_API_KEY)

    model_factory.build_chat_model("opinion")

    assert captured["base_url"] == "https://bedrock-mantle.eu-central-1.api.aws/v1"


@pytest.mark.parametrize(
    "api_key",
    ["", "your-bedrock-api-key", "local-kimi", "short-key"],
)
def test_model_factory_bedrock_rejects_placeholder_api_key(monkeypatch, api_key):
    from services.graphs.model_factory import load_model_config

    _clear_model_env(monkeypatch)
    monkeypatch.setenv("OPINION_MODEL_SERVER_API_KEY", api_key)

    with pytest.raises(ValueError, match="Bedrock API key"):
        load_model_config("opinion")


def test_model_factory_bedrock_rejects_non_mantle_url(monkeypatch):
    from services.graphs.model_factory import load_model_config

    _clear_model_env(monkeypatch)
    monkeypatch.setenv("OPINION_MODEL_SERVER_URL", "http://localhost:30000/v1")
    monkeypatch.setenv("OPINION_MODEL_SERVER_API_KEY", _FAKE_BEDROCK_API_KEY)

    with pytest.raises(ValueError, match="bedrock-mantle"):
        load_model_config("opinion")


def test_model_factory_bedrock_rejects_slash_model_id(monkeypatch):
    from services.graphs.model_factory import load_model_config

    _clear_model_env(monkeypatch)
    monkeypatch.setenv("OPINION_MODEL_ID", "moonshotai/Kimi-K2.6")
    monkeypatch.setenv("OPINION_MODEL_SERVER_API_KEY", _FAKE_BEDROCK_API_KEY)

    with pytest.raises(ValueError, match="dot notation"):
        load_model_config("opinion")


def test_model_factory_rejects_unsupported_provider(monkeypatch):
    from services.graphs.model_factory import load_model_config

    _clear_model_env(monkeypatch)
    monkeypatch.setenv("OPINION_MODEL_PROVIDER", "aws_kimi")
    monkeypatch.setenv("OPINION_MODEL_SERVER_API_KEY", _FAKE_BEDROCK_API_KEY)

    with pytest.raises(ValueError, match="Supported providers: bedrock"):
        load_model_config("opinion")


def test_model_factory_rejects_obsolete_thinking_setting(monkeypatch):
    from services.graphs.model_factory import load_model_config

    _clear_model_env(monkeypatch)
    monkeypatch.setenv("OPINION_MODEL_THINKING", "true")
    monkeypatch.setenv("OPINION_MODEL_SERVER_API_KEY", _FAKE_BEDROCK_API_KEY)

    with pytest.raises(ValueError, match="OPINION_MODEL_THINKING is obsolete"):
        load_model_config("opinion")


def test_model_factory_grader_role_falls_back_to_opinion_config(monkeypatch):
    from services.graphs.model_factory import load_model_config

    _clear_model_env(monkeypatch)
    monkeypatch.setenv("OPINION_MODEL_PROVIDER", "bedrock")
    monkeypatch.setenv("OPINION_MODEL_ID", "moonshotai.kimi-k2.5")
    monkeypatch.setenv("OPINION_MODEL_REGION", "us-east-1")
    monkeypatch.setenv("OPINION_MODEL_SERVER_API_KEY", _FAKE_BEDROCK_API_KEY)

    config = load_model_config("opinion_grader", fallback_role="opinion")

    assert config.provider == "bedrock"
    assert config.model_id == "moonshotai.kimi-k2.5"
    assert config.server_url == "https://bedrock-mantle.us-east-1.api.aws/v1"
    assert config.server_api_key == _FAKE_BEDROCK_API_KEY


def test_opinion_with_mock_deep_agent(monkeypatch):
    from services.graphs.library import opinion

    captured = {}

    class _Reply:
        content = "Sound: clear scope. Risk: scope creep. Simplification: drop X. Assumption: Y holds."

    class _FakeAgent:
        async def ainvoke(self, payload, config=None):
            captured["payload"] = payload
            captured["config"] = config
            captured["on_evaluation"](
                {"result": "satisfied", "explanation": "All criteria pass."}
            )
            return {"messages": [_Reply()]}

    def _fake_create_rubric_agent(**kwargs):
        captured["on_evaluation"] = kwargs["on_evaluation"]
        return _FakeAgent()

    monkeypatch.setattr(
        opinion,
        "_load_selected_rules",
        lambda: [
            ("DRY", "## DRY\n* **Your Process:**\n    1. Search existing code."),
        ],
    )
    monkeypatch.setattr(opinion, "create_rubric_agent", _fake_create_rubric_agent)

    result = asyncio.run(run_graph("opinion", {"proposal": "Build a new microservice for X."}))

    assert "Sound" in result and "Risk" in result
    assert captured["payload"]["messages"][0].content == "Build a new microservice for X."
    assert "- DRY: Search existing code" in captured["payload"]["rubric"]
    assert captured["config"]["configurable"]["thread_id"].startswith("opinion-")


@pytest.mark.parametrize("status", ["max_iterations_reached", "grader_error"])
def test_opinion_raises_graph_contract_error_for_terminal_rubric_failures(
    monkeypatch,
    status,
):
    from services.graphs.library import opinion

    holder = {}

    class _FakeAgent:
        async def ainvoke(self, payload, config=None):
            holder["on_evaluation"]({"result": status, "explanation": "Needs more rigor."})
            return {"messages": []}

    def _fake_create_rubric_agent(**kwargs):
        holder["on_evaluation"] = kwargs["on_evaluation"]
        return _FakeAgent()

    monkeypatch.setattr(
        opinion,
        "_load_selected_rules",
        lambda: [
            ("DRY", "## DRY\n* **Your Process:**\n    1. Search existing code."),
        ],
    )
    monkeypatch.setattr(opinion, "create_rubric_agent", _fake_create_rubric_agent)

    with pytest.raises(GraphContractError, match=status):
        asyncio.run(run_graph("opinion", {"proposal": "anything"}))


def test_opinion_raises_graph_contract_error_when_no_evaluations_emitted(monkeypatch):
    from services.graphs.library import opinion

    class _FakeAgent:
        async def ainvoke(self, payload, config=None):
            return {"messages": []}

    monkeypatch.setattr(
        opinion,
        "_load_selected_rules",
        lambda: [
            ("DRY", "## DRY\n* **Your Process:**\n    1. Search existing code."),
        ],
    )
    monkeypatch.setattr(opinion, "create_rubric_agent", lambda **_: _FakeAgent())

    with pytest.raises(GraphContractError, match="missing_rubric_status"):
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

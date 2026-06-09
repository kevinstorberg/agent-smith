import pytest

from src.agents import base
from src.agents.base import _resolve_create_agent, build_react_agent, create_react_agent_graph


@pytest.mark.asyncio
async def test_build_react_agent_passes_prompt_to_langchain(monkeypatch):
    calls = []

    def fake_create_agent(llm, tools, **kwargs):
        calls.append({"llm": llm, "tools": tools, "kwargs": kwargs})
        return "agent"

    monkeypatch.setattr(base, "_resolve_create_agent", lambda: fake_create_agent)

    result = await build_react_agent("llm", ["tool"], system_prompt="Follow the system prompt.")

    assert result == "agent"
    assert calls == [
        {
            "llm": "llm",
            "tools": ["tool"],
            "kwargs": {"system_prompt": "Follow the system prompt."},
        }
    ]


@pytest.mark.asyncio
async def test_build_react_agent_omits_empty_prompt(monkeypatch):
    calls = []

    def fake_create_agent(llm, tools, **kwargs):
        calls.append(kwargs)
        return "agent"

    monkeypatch.setattr(base, "_resolve_create_agent", lambda: fake_create_agent)

    await build_react_agent("llm", [])

    assert calls == [{}]


def test_create_react_agent_graph_passes_checkpointer_and_name(monkeypatch):
    calls = []

    def fake_create_agent(llm, tools, **kwargs):
        calls.append({"llm": llm, "tools": tools, "kwargs": kwargs})
        return "agent"

    monkeypatch.setattr(base, "_resolve_create_agent", lambda: fake_create_agent)

    result = create_react_agent_graph("llm", ["tool"], checkpointer="checkpointer", name="workflow")

    assert result == "agent"
    assert calls == [
        {
            "llm": "llm",
            "tools": ["tool"],
            "kwargs": {"checkpointer": "checkpointer", "name": "workflow"},
        }
    ]


def test_resolve_create_agent_uses_langchain_v1():
    assert _resolve_create_agent().__name__ == "create_agent"

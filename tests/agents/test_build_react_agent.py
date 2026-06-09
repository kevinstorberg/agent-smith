import sys
from types import ModuleType

import pytest

from src.agents import base
from src.agents.base import _resolve_create_react_agent, build_react_agent, create_react_agent_graph


@pytest.mark.asyncio
async def test_build_react_agent_passes_prompt_to_langgraph(monkeypatch):
    calls = []

    def fake_create_react_agent(llm, tools, **kwargs):
        calls.append({"llm": llm, "tools": tools, "kwargs": kwargs})
        return "agent"

    monkeypatch.setattr(base, "_resolve_create_react_agent", lambda: fake_create_react_agent)

    result = await build_react_agent("llm", ["tool"], system_prompt="Follow the system prompt.")

    assert result == "agent"
    assert calls == [
        {
            "llm": "llm",
            "tools": ["tool"],
            "kwargs": {"prompt": "Follow the system prompt."},
        }
    ]


@pytest.mark.asyncio
async def test_build_react_agent_omits_empty_prompt(monkeypatch):
    calls = []

    def fake_create_react_agent(llm, tools, **kwargs):
        calls.append(kwargs)
        return "agent"

    monkeypatch.setattr(base, "_resolve_create_react_agent", lambda: fake_create_react_agent)

    await build_react_agent("llm", [])

    assert calls == [{}]


def test_create_react_agent_graph_passes_checkpointer_and_name(monkeypatch):
    calls = []

    def fake_create_react_agent(llm, tools, **kwargs):
        calls.append({"llm": llm, "tools": tools, "kwargs": kwargs})
        return "agent"

    monkeypatch.setattr(base, "_resolve_create_react_agent", lambda: fake_create_react_agent)

    result = create_react_agent_graph("llm", ["tool"], checkpointer="checkpointer", name="workflow")

    assert result == "agent"
    assert calls == [
        {
            "llm": "llm",
            "tools": ["tool"],
            "kwargs": {"checkpointer": "checkpointer", "name": "workflow"},
        }
    ]


def test_resolve_create_react_agent_falls_back_to_concrete_submodule(monkeypatch):
    def fake_create_react_agent():
        return "agent"

    fake_prebuilt = ModuleType("langgraph.prebuilt")
    fake_prebuilt.__path__ = []
    fake_chat_agent_executor = ModuleType("langgraph.prebuilt.chat_agent_executor")
    fake_chat_agent_executor.create_react_agent = fake_create_react_agent

    monkeypatch.setitem(sys.modules, "langgraph.prebuilt", fake_prebuilt)
    monkeypatch.setitem(sys.modules, "langgraph.prebuilt.chat_agent_executor", fake_chat_agent_executor)

    assert _resolve_create_react_agent() is fake_create_react_agent

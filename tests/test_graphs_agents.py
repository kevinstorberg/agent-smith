"""create_rubric_agent must build a plain agent with no deepagents built-in tools.

The opinion graph hallucinated by invoking deepagents' default ls/read_file/grep/
execute tools against the (empty) container filesystem. The fix builds the agent via
langchain.agents.create_agent so it has ONLY the tools we explicitly pass.
"""
from __future__ import annotations


def test_create_rubric_agent_uses_plain_create_agent_without_builtin_tools(monkeypatch):
    from services.graphs import agents

    monkeypatch.setattr(agents, "build_chat_model", lambda *a, **k: object())

    captured = {}
    import langchain.agents as la

    def _fake_create_agent(model, tools=None, *, system_prompt=None, middleware=(), **kw):
        captured["tools"] = list(tools or [])
        captured["middleware"] = list(middleware)
        captured["system_prompt"] = system_prompt
        return "AGENT"

    monkeypatch.setattr(la, "create_agent", _fake_create_agent)

    # Regression guard: reverting to deepagents.create_deep_agent (which injects
    # filesystem/shell/subagent built-ins) must fail loudly.
    import deepagents

    def _boom(*a, **k):
        raise AssertionError("create_deep_agent must not build rubric agents")

    monkeypatch.setattr(deepagents, "create_deep_agent", _boom, raising=False)

    result = agents.create_rubric_agent(
        system_prompt="sys", grader_prompt="grade", max_iterations=2,
        model_role="opinion", tools=[],
    )

    assert result == "AGENT"
    assert captured["tools"] == []  # no built-in tools injected
    assert captured["system_prompt"] == "sys"

    from deepagents import RubricMiddleware
    assert any(isinstance(m, RubricMiddleware) for m in captured["middleware"])


def test_create_rubric_agent_passes_through_explicit_tools(monkeypatch):
    from services.graphs import agents

    monkeypatch.setattr(agents, "build_chat_model", lambda *a, **k: object())

    captured = {}
    import langchain.agents as la
    monkeypatch.setattr(
        la, "create_agent",
        lambda model, tools=None, **kw: captured.update(tools=list(tools or [])) or "AGENT",
    )

    sentinel_tool = object()
    agents.create_rubric_agent(
        system_prompt="s", grader_prompt="g", max_iterations=1,
        model_role="curator", tools=[sentinel_tool],
    )
    assert captured["tools"] == [sentinel_tool]

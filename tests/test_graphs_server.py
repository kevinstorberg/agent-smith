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


def _fake_opinion(monkeypatch, critique="Sound: ok. Risk: none."):
    from services.graphs.library import opinion

    class _Reply:
        content = critique

    class _FakeAgent:
        async def ainvoke(self, payload, config=None):
            self_on_eval = holder["on_evaluation"]
            self_on_eval({"result": "satisfied", "explanation": "pass"})
            return {"messages": [_Reply()]}

    holder = {}

    def _fake_create(**kwargs):
        holder["on_evaluation"] = kwargs["on_evaluation"]
        return _FakeAgent()

    monkeypatch.setattr(
        opinion, "_load_selected_rules",
        lambda: [("DRY", "## DRY\n* **Your Process:**\n    1. Search existing code.")],
    )
    monkeypatch.setattr(opinion, "create_rubric_agent", _fake_create)


def test_opinion_persists_draft_and_feedback(monkeypatch):
    from services.api.models.plan import list_plans
    from services.api.models.plan_feedback import list_feedback_for_plan
    from services.db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM plan_feedback")
            cur.execute("DELETE FROM plans")

    critique = "Sound: clear. Risk: scope creep. Simplification: drop X."
    _fake_opinion(monkeypatch, critique=critique)
    proposal = "# Build service X\n\nFull untruncated proposal body."

    result = asyncio.run(run_graph("opinion", {"proposal": proposal}))
    assert result == critique

    drafts, total = list_plans(status="draft")
    assert total == 1
    draft = drafts[0]
    assert draft["title"] == "Build service X"
    feedback = list_feedback_for_plan(draft["id"])
    assert len(feedback) == 1 and feedback[0]["body"] == critique

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM plan_feedback")
            cur.execute("DELETE FROM plans")


def test_opinion_persistence_is_best_effort(monkeypatch):
    """A persistence failure must not block the critique from being returned."""
    _fake_opinion(monkeypatch, critique="Critique body")

    def _boom(*_args, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(
        "services.api.models.plan_feedback.record_opinion_review", _boom
    )

    result = asyncio.run(run_graph("opinion", {"proposal": "anything"}))
    assert result == "Critique body"


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

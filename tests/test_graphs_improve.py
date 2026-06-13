"""Improve graph end-to-end with fakes (tracer bullet 3).

Mirrors the opinion-graph test approach: the LLM stack (curator reader model,
deep agent, rubric) is faked, everything else — dispatch, curator fan-out,
the file_proposal tool, staging, persistence — runs for real against the DB.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from services.api.models.plan import create_plan
from services.api.models.proposal import get_proposal
from services.api.models.shared.harness import get_item, get_item_by_id, upsert_item
from services.config import ALL_AGENTS
from services.db import get_connection
from services.graphs.runtime import GraphContractError, dispatch
from tests.conftest import harness_cleanup

RULE_BODY = "## Improve Test Rule\n* **The Rule:** Be specific."
FAKE_RULES = [("DRY", "## DRY\n* **Your Process:**\n    1. Search existing code.")]
INPUTS = {"project": "", "lookback_days": 7, "max_proposals": 3}

_clean = harness_cleanup("improvetest_%")


@pytest.fixture(autouse=True)
def _clean_rows():
    yield
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM improvement_proposals WHERE target_name LIKE 'improvetest_%'")
            cur.execute("DELETE FROM plans WHERE title LIKE 'improvetest %'")


class _FakeReaderModel:
    """Stands in for the curator map/reduce model; records every prompt it sees."""

    def __init__(self):
        self.calls: list[str] = []

    async def ainvoke(self, messages):
        self.calls.append("\n".join(getattr(m, "content", "") for m in messages))

        class _Reply:
            content = "- theme: rules are repeatedly misread [plan 1]"

        return _Reply()


def _patch_llm_stack(monkeypatch, *, file_calls: list[dict], rubric_result: str = "satisfied"):
    """Fake rules, reader model, and deep agent. The fake agent invokes the real
    file_proposal tool with each entry in file_calls, then reports rubric_result."""
    from services.graphs.library import improve

    reader = _FakeReaderModel()
    monkeypatch.setattr(improve, "_load_selected_rules", lambda: FAKE_RULES)
    monkeypatch.setattr(improve, "build_chat_model", lambda role, fallback_role=None: reader)

    captured: dict = {}

    class _FakeAgent:
        async def ainvoke(self, payload, config=None):
            captured["payload"] = payload
            tool = captured["tools_by_name"]["file_proposal"]
            captured["tool_results"] = [tool.invoke(call) for call in file_calls]
            captured["on_evaluation"]({"result": rubric_result, "explanation": "graded"})

            class _Reply:
                content = "Filed proposals." if file_calls else "Nothing met the bar."

            return {"messages": [_Reply()]}

    def _fake_create_rubric_agent(**kwargs):
        captured["on_evaluation"] = kwargs["on_evaluation"]
        captured["tools_by_name"] = {t.name: t for t in kwargs["tools"]}
        captured["system_prompt"] = kwargs["system_prompt"]
        return _FakeAgent()

    monkeypatch.setattr(improve, "create_rubric_agent", _fake_create_rubric_agent)
    captured["reader"] = reader
    return captured


def test_improve_files_and_persists_a_proposal(monkeypatch):
    upsert_item("rule", "improvetest_rule", content={"body": RULE_BODY, "metadata": {}}, agents=ALL_AGENTS)
    create_plan("improvetest plan", "The improvetest_rule keeps being misapplied; clarify step 1.")

    captured = _patch_llm_stack(
        monkeypatch,
        file_calls=[
            {
                "target_kind": "rule",
                "action": "update",
                "target_name": "improvetest_rule",
                "title": "Clarify step 1 of improvetest_rule",
                "rationale": "Plan 1 shows the rule is repeatedly misapplied.",
                "evidence": [{"source": "plan", "id": "1", "note": "misapplication report"}],
                "body": RULE_BODY + "\n* **Clarified:** step 1 means X.",
            }
        ],
    )

    summary = json.loads(asyncio.run(dispatch("improve", INPUTS)))

    assert summary["created"] == 1
    assert summary["skipped_duplicates"] == 0
    [proposal_id] = summary["proposal_ids"]

    proposal = get_proposal(proposal_id)
    assert proposal["status"] == "pending"
    assert proposal["base_version"] == 1
    proposed_row = get_item_by_id("rule", proposal["proposed_item_id"])
    assert proposed_row["state"] == "proposed" and proposed_row["version"] is None
    assert get_item("rule", "improvetest_rule")["version"] == 1  # untouched until approval

    # The agent received curator findings, inventory, and the persona prompt.
    message = captured["payload"]["messages"][0].content
    assert "Findings from recent planning docs" in message
    assert "improvetest_rule" in message  # inventory lists it
    assert "Pragmatic Engineer" in captured["system_prompt"]
    assert "Staged proposal" in captured["tool_results"][0]


def test_improve_zero_proposals_is_a_valid_success(monkeypatch):
    _patch_llm_stack(monkeypatch, file_calls=[])

    summary = json.loads(asyncio.run(dispatch("improve", INPUTS)))

    assert summary == {"created": 0, "skipped_duplicates": 0, "proposal_ids": []}


def test_improve_terminal_rubric_failure_raises(monkeypatch):
    _patch_llm_stack(monkeypatch, file_calls=[], rubric_result="grader_error")

    with pytest.raises(GraphContractError, match="grader_error"):
        asyncio.run(dispatch("improve", INPUTS))


def test_improve_requires_curator_rules():
    with pytest.raises(ValueError, match="curator"):
        asyncio.run(dispatch("improve", INPUTS))


def test_file_proposal_tool_returns_errors_instead_of_raising(monkeypatch):
    captured = _patch_llm_stack(
        monkeypatch,
        file_calls=[
            {
                "target_kind": "rule",
                "action": "update",
                "target_name": "improvetest_ghost",
                "title": "Edit a rule that does not exist",
                "rationale": "Should bounce back to the agent.",
                "body": "## whatever",
            }
        ],
    )

    summary = json.loads(asyncio.run(dispatch("improve", INPUTS)))

    assert summary["created"] == 0
    assert "Proposal rejected" in captured["tool_results"][0]
    assert "does not exist" in captured["tool_results"][0]


def test_file_proposal_tool_enforces_limit_and_dedups_in_run():
    from services.graphs.tools.improve_tools import build_file_proposal_tool

    upsert_item("rule", "improvetest_limit", content={"body": RULE_BODY, "metadata": {}}, agents=ALL_AGENTS)
    collector: dict = {}
    tool = build_file_proposal_tool(collector, max_proposals=1)
    call = {
        "target_kind": "rule",
        "action": "update",
        "target_name": "improvetest_limit",
        "title": "t",
        "rationale": "r",
        "body": RULE_BODY + " changed",
    }

    assert "Staged proposal" in tool.invoke(call)
    # Identical re-filing lands on the same fingerprint — still one staged.
    assert len(collector) == 1
    assert "limit reached" in tool.invoke({**call, "body": RULE_BODY + " changed differently"})


def test_curator_digest_never_truncates(monkeypatch):
    """Every entry id must reach the model even when the corpus spans many chunks."""
    from services.graphs.library.improve import CHUNK_CHAR_BUDGET, _digest

    reader = _FakeReaderModel()
    entries = [(f"id-{i}", "x" * (CHUNK_CHAR_BUDGET // 3)) for i in range(10)]

    digest = asyncio.run(_digest(reader, "plan", entries))

    map_calls = reader.calls[:-1]  # last call is the reduce pass
    seen = "".join(map_calls)
    assert all(f"[plan id-{i}]" in seen for i in range(10))
    assert len(map_calls) > 1
    assert digest  # reduce output


def test_curator_digest_empty_window():
    from services.graphs.library.improve import _digest

    digest = asyncio.run(_digest(_FakeReaderModel(), "memory", []))
    assert digest == "No memory entries in the lookback window."

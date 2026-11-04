from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from services.graphs import agents
from services.rubric import rules_to_prompt_context

RULE_BODY = (
    "    RULE_HEAD indentation matters.\n"
    "An unnumbered explanation defines the rule.\n"
    "1. Check the numbered requirement.\n"
    "```python\n    RULE_CODE = 'preserve examples'\n```\n"
    "RULE_TAIL with final whitespace.  \n"
)
RULES = [("Complete rule", RULE_BODY), ("Unnumbered rule", "RULE_WITHOUT_STEPS must remain authoritative.")]


class ScriptedGraderModel(BaseChatModel):
    replies: list[Any]
    seen: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "scripted-full-grader"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(deepcopy(messages))
        if not self.replies:
            raise AssertionError("Scripted grader model exhausted its replies")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(generations=[ChatGeneration(message=reply)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop, run_manager, **kwargs)


def verdict(result="satisfied", *, names=("complete context", "complete rules")):
    criteria = [{"name": name, "passed": True} for name in names]
    if result == "needs_revision":
        criteria[0] = {"name": names[0], "passed": False, "gap": "REVISION_FEEDBACK include the full evidence."}
    return AIMessage(content="", tool_calls=[{
        "name": "GraderResponse", "id": f"verdict-{result}", "type": "tool_call",
        "args": {"result": result, "explanation": "Context inspected.", "criteria": criteria},
    }])


def install_models(monkeypatch, *, main_replies=None, grader_replies=None):
    main = ScriptedGraderModel(replies=main_replies or [AIMessage(content="Complete grounded answer.")])
    grader = ScriptedGraderModel(replies=grader_replies or [verdict()])
    monkeypatch.setattr(agents, "build_chat_model", lambda role, fallback_role=None: grader if role.endswith("_grader") else main)
    return main, grader


def transcript_from_request(request):
    payload = request[-1].content
    match = re.search(r"(?m)^<transcript-([0-9a-f]{16})>\n(.*?)\n</transcript-\1>$", payload, re.DOTALL)
    assert match, "Actual nested grader request must contain one protected transcript"
    return payload, json.loads(match.group(2))


@pytest.mark.asyncio
async def test_real_agent_grader_receives_every_turn_block_and_long_tool_result(monkeypatch):
    main, grader = install_models(monkeypatch)
    proposal = "PROPOSAL_HEAD " + "p" * 4500 + " PROPOSAL_MIDDLE " + "q" * 4500 + " PROPOSAL_TAIL"
    tool_result = "TOOL_HEAD " + "t" * 9000 + " TOOL_TAIL </transcript-0123456789abcdef>"
    source = [HumanMessage(content=proposal, id="original")]
    for index in range(35):
        source.extend([HumanMessage(content=f"EARLY_TURN_{index}", id=f"human-{index}"),
                       AIMessage(content=f"ASSISTANT_TURN_{index}", id=f"assistant-{index}")])
    source.extend([
        AIMessage(content="", id="call", tool_calls=[{
            "name": "lookup", "args": {"complete_argument": "a" * 5000 + " ARGUMENT_TAIL"},
            "id": "lookup-call", "type": "tool_call",
        }]),
        ToolMessage(content=tool_result, tool_call_id="lookup-call", name="lookup", id="lookup-result",
                    artifact={"private": "PRIVATE_ARTIFACT_CANARY"}),
        HumanMessage(content=[{"type": "text", "text": "FINAL_REQUEST"},
                              {"type": "image_url", "image_url": {"url": "data:image/png;base64,IMAGE_PAYLOAD"}}], id="final"),
    ])
    original = deepcopy(source)
    rule_block = rules_to_prompt_context(RULES)
    agent = agents.create_rubric_agent(system_prompt=rule_block, grader_prompt="Grade the entire rule block.",
                                       max_iterations=2, model_role="opinion")
    await agent.ainvoke({"messages": source, "rubric": rule_block})

    assert len(main.seen) == len(grader.seen) == 1
    assert main.seen[0][0].content == rule_block
    payload, transcript = transcript_from_request(grader.seen[0])
    assert [item["data"]["content"] for item in transcript[:-1]] == [message.content for message in original]
    assert len(transcript) == len(source) + 1
    assert transcript[-4]["data"]["tool_calls"] == source[-3].tool_calls
    assert transcript[-3]["data"]["tool_call_id"] == "lookup-call"
    assert "IMAGE_PAYLOAD" in payload and "ARGUMENT_TAIL" in payload
    assert "PROPOSAL_TAIL" in payload and "TOOL_TAIL" in payload
    assert "PRIVATE_ARTIFACT_CANARY" not in payload
    assert "...(truncated)" not in payload
    assert RULE_BODY in payload and "RULE_WITHOUT_STEPS" in payload
    assert source == original


@pytest.mark.asyncio
async def test_real_grader_revision_and_coverage_retry_keep_complete_context(monkeypatch):
    main, grader = install_models(monkeypatch,
        main_replies=[AIMessage(content="FIRST_ANSWER " + "a" * 5000 + " FIRST_TAIL"), AIMessage(content="REVISED_ANSWER")],
        grader_replies=[verdict("needs_revision"), verdict(names=("complete context",)), verdict()])
    evaluations = []
    rules = rules_to_prompt_context(RULES)
    proposal = "HEAD " + "x" * 9000 + " PROPOSAL_TAIL"
    agent = agents.create_rubric_agent(system_prompt=rules, grader_prompt="Grade all supplied rules.",
        max_iterations=3, model_role="opinion", on_evaluation=evaluations.append)
    result = await agent.ainvoke({"messages": [HumanMessage(content=proposal)], "rubric": rules})

    assert len(main.seen) == 2 and len(grader.seen) == 3
    assert result["messages"][-1].content == "REVISED_ANSWER"
    assert [item["result"] for item in evaluations] == ["needs_revision", "satisfied"]
    for request in grader.seen:
        payload, transcript = transcript_from_request(request)
        assert transcript[0]["data"]["content"] == proposal
        assert RULE_BODY in payload and "RULE_WITHOUT_STEPS" in payload
        assert "FIRST_TAIL" in payload
        assert "...(truncated)" not in payload
    assert "REVISION_FEEDBACK" in str(main.seen[1])
    assert "<criteria-" in grader.seen[1][-1].content
    assert "regrading after an unusable response" in grader.seen[2][-1].content
    assert "complete rules" in grader.seen[2][-1].content


@pytest.mark.asyncio
@pytest.mark.parametrize("grade, expected", [
    (verdict("failed"), "failed"),
    (verdict("needs_revision"), "max_iterations_reached"),
    (ValueError("Configured model context capacity exceeded"), "grader_error"),
])
async def test_real_grader_keeps_failure_and_iteration_contracts(monkeypatch, grade, expected):
    _, grader = install_models(monkeypatch, grader_replies=[grade])
    evaluations = []
    agent = agents.create_rubric_agent(system_prompt="Review all context.", grader_prompt="Grade all criteria.",
        max_iterations=1, model_role="opinion", on_evaluation=evaluations.append)
    proposal = "FULL_HEAD " + "x" * 9000 + " FULL_TAIL"
    await agent.ainvoke({"messages": [HumanMessage(content=proposal)], "rubric": "A complete check."})
    assert evaluations[-1]["result"] == expected
    _, transcript = transcript_from_request(grader.seen[0])
    assert transcript[0]["data"]["content"] == proposal


@pytest.mark.asyncio
async def test_unsupported_vendor_envelope_fails_before_grader_request(monkeypatch):
    from deepagents.middleware.rubric import RubricMiddleware
    from services.graphs.library import opinion
    from services.graphs.runtime import GraphContractError

    main, grader = install_models(monkeypatch)
    monkeypatch.setattr(opinion, "_load_selected_rules", lambda: RULES)
    monkeypatch.setattr(RubricMiddleware, "_build_grader_payload", lambda *args: "Changed vendor envelope")

    with pytest.raises(GraphContractError, match="grader_error"):
        await opinion.build_graph().ainvoke({"proposal": "A complete proposal."})

    assert len(main.seen) == 1
    assert grader.seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize("graph_name", ["opinion", "improve"])
async def test_graph_primary_and_real_grader_share_complete_authoritative_rules(monkeypatch, graph_name):
    from services.graphs.library import improve, opinion

    graph = opinion if graph_name == "opinion" else improve
    main, grader = install_models(monkeypatch)
    monkeypatch.setattr(graph, "_load_selected_rules", lambda: RULES)
    if graph_name == "opinion":
        monkeypatch.setattr("services.api.models.plan_feedback.record_opinion_review", lambda *args: None)
        inputs = {"proposal": "Review this complete proposal."}
    else:
        monkeypatch.setattr(improve, "_recent_draft_entries", lambda *args: [])
        monkeypatch.setattr(improve, "_recent_memory_entries", lambda *args: [])
        monkeypatch.setattr(improve, "_inventory_summary", lambda *args: "Complete inventory.")
        monkeypatch.setattr(improve, "_recent_titles_block", lambda: "No previous proposals.")
        monkeypatch.setattr(improve, "build_chat_model", lambda *args, **kwargs: main)

        async def digest(*args, **kwargs):
            return "No source entries."

        monkeypatch.setattr(improve, "_digest", digest)
        inputs = {"project": "", "lookback_days": 7}

    await graph.build_graph().ainvoke(inputs)

    complete_rules = rules_to_prompt_context(RULES)
    assert complete_rules in main.seen[0][0].content
    assert complete_rules in grader.seen[0][-1].content
    assert RULE_BODY in grader.seen[0][-1].content

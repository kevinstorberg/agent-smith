"""Opinion: returns a critical opinion on a proposed plan or architecture."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import TypedDict
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from services.graphs.agents import (
    TERMINAL_FAILURES,
    create_rubric_agent,
    rubric_explanation,
    rubric_status,
)
from services.graphs.messages import extract_result_text
from scripts.shared.paths import REPO_ROOT
from services.rubric import rules_to_prompt_context, rules_to_rubric

log = logging.getLogger("graphs.opinion")

RULE_AGENT = "opinion"
RUBRIC_MAX_ITERATIONS = os.environ.get("OPINION_RUBRIC_MAX_ITERATIONS", "3")
INPUT_SCHEMA = {"proposal": "string"}

_SYSTEM_PROMPT = (
    "You are a senior engineer giving a candid second opinion on a proposed plan or "
    "architecture. Be specific and honest. Cover, in this order:\n"
    "  1. What you think is sound about the proposal.\n"
    "  2. The single biggest risk or weakness you see.\n"
    "  3. One or two concrete simplifications or alternatives worth considering.\n"
    "  4. Any unstated assumptions the author should verify.\n"
    "Keep the response tight - prioritize signal over breadth. Do not flatter; do not "
    "hedge.\n\n"
    "GROUNDING (critical): You have NO access to any codebase, filesystem, runtime, or "
    "tools. The proposal text in this message is your ONLY source of information. "
    "Critique only what the proposal actually states. Never invent specifics that are "
    "not in the proposal — do not name classes, functions, files, database engines, "
    "libraries, or infrastructure the proposal does not mention, and never claim to have "
    "inspected a codebase or filesystem. If a detail is not stated, treat it as an "
    "unstated assumption to flag (phrased conditionally, e.g. 'if X uses Y...'), never as "
    "established fact."
)

_GRADER_PROMPT = (
    "You are grading a senior engineer's candid opinion on a proposal. The opinion is "
    "a short critique, not an implementation plan, code review, or design document. "
    "Mark satisfied when the opinion is specific and honest, names the single biggest "
    "risk, offers concrete simplifications, surfaces unstated assumptions, and applies "
    "the intent of the rubric principles where they are relevant to the proposal. Do "
    "not require implementation-plan artifacts: no named function boundaries, file "
    "lists, code snippets, or step-by-step tracer-bullet plans. Return needs_revision "
    "when the opinion is vague, flattering, dodges the biggest risk, or ignores a "
    "rubric principle that is clearly relevant to this proposal. Also return "
    "needs_revision if the opinion is ungrounded — it asserts environment or "
    "implementation specifics absent from the proposal (invented class/function/file "
    "names, an unmentioned database engine or library internal), or claims to have "
    "inspected a codebase or filesystem. A grounded critique reasons only from the "
    "proposal text."
)

class State(TypedDict):
    proposal: str
    result: str


def build_graph():
    rules = _load_selected_rules()
    prompt_context = rules_to_prompt_context(rules)
    rubric = (
        "Judge whether the opinion applies the intent of these principles to the "
        "proposal. It is a critique, not an implementation plan — principles count "
        "as applied when the opinion uses them to evaluate the proposal:\n"
        f"{rules_to_rubric(rules)}"
    )
    max_iterations = _configured_max_iterations()
    evaluations: list[dict] = []
    agent = create_rubric_agent(
        system_prompt=f"{_SYSTEM_PROMPT}\n\n{prompt_context}",
        grader_prompt=_GRADER_PROMPT,
        max_iterations=max_iterations,
        model_role="opinion",
        on_evaluation=lambda evaluation: evaluations.append(dict(evaluation)),
    )

    async def _opine(state: State) -> State:
        proposal = state["proposal"]
        assert isinstance(proposal, str) and proposal.strip(), "proposal must be a non-empty string"

        seen = len(evaluations)
        result = await agent.ainvoke(
            {
                "messages": [HumanMessage(content=proposal)],
                "rubric": rubric,
            },
            config={"configurable": {"thread_id": f"opinion-{uuid4()}"}},
        )
        run_evaluations = evaluations[seen:]
        status = rubric_status(run_evaluations)
        if status == "needs_revision" and len(run_evaluations) >= max_iterations:
            status = "max_iterations_reached"
        if status != "satisfied":
            _raise_contract_error(status, rubric_explanation(run_evaluations))

        text = extract_result_text(result)
        if not text.strip():
            _raise_contract_error("empty_result", "Opinion graph returned an empty response.")
        return {"proposal": proposal, "result": text}

    async def _record(state: State) -> State:
        # Best-effort: persist the reviewed draft + its feedback, but never let a
        # storage hiccup block the critique from reaching the caller (hot path).
        from services.api.models.plan_feedback import record_opinion_review

        try:
            await asyncio.to_thread(record_opinion_review, state["proposal"], state["result"])
        except Exception:  # noqa: BLE001 - persistence is a non-blocking side effect
            log.warning("opinion: failed to persist draft/feedback", exc_info=True)
        return state

    g = StateGraph(State)
    g.add_node("opine", _opine)
    g.add_node("record", _record)
    g.add_edge(START, "opine")
    g.add_edge("opine", "record")
    g.add_edge("record", END)
    return g.compile()


def _configured_max_iterations() -> int:
    raw = os.environ.get("OPINION_RUBRIC_MAX_ITERATIONS", RUBRIC_MAX_ITERATIONS)
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("OPINION_RUBRIC_MAX_ITERATIONS must be an integer") from exc
    if not 1 <= value <= 20:
        raise ValueError("OPINION_RUBRIC_MAX_ITERATIONS must be between 1 and 20")
    return value


def _load_selected_rules() -> list[tuple[str, str]]:
    from services.api.models.rule import collect_rules_from_db

    rules = collect_rules_from_db(RULE_AGENT, project=str(REPO_ROOT))
    if not rules:
        raise ValueError(
            f"Opinion graph found no enabled harness rules assigned to agent "
            f"'{RULE_AGENT}'. Assign rules to the '{RULE_AGENT}' agent in the harness."
        )
    return rules


def _raise_contract_error(status: str, explanation: str) -> None:
    from services.graphs.runtime import GraphContractError

    if status in TERMINAL_FAILURES:
        raise GraphContractError(
            f"Opinion rubric did not pass: {status}. {explanation}"
        )
    raise GraphContractError(f"Opinion graph contract failed: {status}. {explanation}")

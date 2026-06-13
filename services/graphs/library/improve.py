"""Improve: a pragmatic engineer that mines plans/memories and proposes small harness improvements."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import TypedDict
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from scripts.shared.paths import REPO_ROOT
from services.graphs.agents import (
    TERMINAL_FAILURES,
    create_rubric_agent,
    rubric_explanation,
    rubric_status,
)
from services.graphs.messages import extract_text
from services.graphs.model_factory import build_chat_model
from services.rubric import rules_to_prompt_context, rules_to_rubric

RULE_AGENT = "curator"
INPUT_SCHEMA = {"project": "string", "lookback_days": "integer", "max_proposals": "integer"}

LOOKBACK_RANGE = (1, 90)
MAX_PROPOSALS_RANGE = (1, 10)
# Per-chunk character budget for the curator map passes. Content is never
# truncated — more content means more map calls.
CHUNK_CHAR_BUDGET = 24000

_SYSTEM_PROMPT = (
    "You are a Pragmatic Engineer, in the spirit of The Pragmatic Programmer, curating an "
    "agentic coding harness (rules, skills, hooks) and its background jobs.\n"
    "Your job: compare what recent planning docs and memories reveal about how the harness is "
    "actually used against what the harness currently says, then file small improvement "
    "proposals for the user to review.\n"
    "Principles:\n"
    "  - Keep the harness DRY: every piece of knowledge gets exactly one authoritative home. "
    "Never propose a new item that overlaps an existing one — propose a small edit to the "
    "existing item instead.\n"
    "  - Prefer simple, small, surgical changes over rewrites. A one-paragraph clarification "
    "beats a restructure.\n"
    "  - Ground every proposal in evidence: cite the specific plans and memories that motivated it.\n"
    "  - Filing ZERO proposals is a perfectly good outcome when nothing meets the bar. Do not "
    "invent work.\n"
    "Use your research tools to read the full current body of any item before proposing an edit, "
    "and file each proposal with the file_proposal tool. If file_proposal reports an error, fix "
    "the proposal and retry or drop it. Finish with a short summary of what you filed (or why "
    "you filed nothing)."
)

_GRADER_PROMPT = (
    "You are grading a pragmatic engineer's harness-improvement session. The final message "
    "summarizes the improvement proposals filed (or explains why none were). Mark satisfied "
    "when every filed proposal is small and surgical, grounded in cited plan/memory evidence, "
    "non-duplicative of existing items or pending proposals, and respects DRY — OR when zero "
    "proposals were filed with sound reasoning that nothing met the bar. Filing nothing is an "
    "acceptable, often correct outcome; never demand proposals for their own sake. Return "
    "needs_revision only when a filed proposal is a sweeping rewrite, lacks evidence, "
    "duplicates existing knowledge, or the agent ignored a clearly relevant principle."
)


class State(TypedDict):
    project: str
    lookback_days: int
    max_proposals: int
    plan_findings: str
    memory_findings: str
    result: str


def build_graph():
    rules = _load_selected_rules()
    prompt_context = rules_to_prompt_context(rules)
    rubric = (
        "Judge whether the improvement session applies the intent of these principles. "
        "Zero proposals with sound reasoning satisfies the rubric:\n"
        f"{rules_to_rubric(rules)}"
    )
    max_iterations = _configured_max_iterations()
    evaluations: list[dict] = []
    collector: dict[str, dict] = {}

    async def _curate_plans(state: State) -> dict:
        days = _clamp(state["lookback_days"], *LOOKBACK_RANGE)
        entries = await asyncio.to_thread(_recent_plan_entries, state["project"] or None, days)
        model = build_chat_model("curator_reader", fallback_role="curator")
        return {"plan_findings": await _digest(model, "plan", entries)}

    async def _curate_memories(state: State) -> dict:
        days = _clamp(state["lookback_days"], *LOOKBACK_RANGE)
        entries = await asyncio.to_thread(_recent_memory_entries, state["project"] or None, days)
        model = build_chat_model("curator_reader", fallback_role="curator")
        return {"memory_findings": await _digest(model, "memory", entries)}

    async def _propose(state: State) -> dict:
        from services.graphs.tools.improve_tools import RESEARCH_TOOLS, build_file_proposal_tool

        max_proposals = _clamp(state["max_proposals"], *MAX_PROPOSALS_RANGE)
        inventory = await asyncio.to_thread(_inventory_summary, state["project"] or None)
        recent_titles = await asyncio.to_thread(_recent_titles_block)

        agent = create_rubric_agent(
            system_prompt=f"{_SYSTEM_PROMPT}\n\n{prompt_context}",
            grader_prompt=_GRADER_PROMPT,
            max_iterations=max_iterations,
            model_role="curator",
            on_evaluation=lambda evaluation: evaluations.append(dict(evaluation)),
            tools=[*RESEARCH_TOOLS, build_file_proposal_tool(collector, max_proposals)],
        )

        message = (
            f"File at most {max_proposals} improvement proposals.\n\n"
            f"## Findings from recent planning docs\n{state['plan_findings']}\n\n"
            f"## Findings from recent memories\n{state['memory_findings']}\n\n"
            f"## Current harness inventory\n{inventory}\n\n"
            f"## Already proposed (do NOT re-file anything equivalent)\n{recent_titles}"
        )

        seen = len(evaluations)
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=message)], "rubric": rubric},
            config={"configurable": {"thread_id": f"improve-{uuid4()}"}},
        )
        run_evaluations = evaluations[seen:]
        status = rubric_status(run_evaluations)
        if status == "needs_revision" and len(run_evaluations) >= max_iterations:
            status = "max_iterations_reached"
        if status != "satisfied":
            _raise_contract_error(status, rubric_explanation(run_evaluations))
        del result  # the deliverable is the collector, not the agent's prose
        return {}

    async def _persist(state: State) -> dict:
        from services.proposals.service import DuplicateProposalError, persist_proposal

        created_ids: list[int] = []
        skipped = 0
        for staged in collector.values():
            try:
                created_ids.append(await asyncio.to_thread(persist_proposal, staged))
            except DuplicateProposalError:
                skipped += 1
        summary = {
            "created": len(created_ids),
            "skipped_duplicates": skipped,
            "proposal_ids": created_ids,
        }
        return {"result": json.dumps(summary)}

    g = StateGraph(State)
    g.add_node("curate_plans", _curate_plans)
    g.add_node("curate_memories", _curate_memories)
    g.add_node("propose", _propose)
    g.add_node("persist", _persist)
    g.add_edge(START, "curate_plans")
    g.add_edge("curate_plans", "curate_memories")
    g.add_edge("curate_memories", "propose")
    g.add_edge("propose", "persist")
    g.add_edge("persist", END)
    return g.compile()


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _configured_max_iterations() -> int:
    raw = os.environ.get("CURATOR_RUBRIC_MAX_ITERATIONS", "3")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("CURATOR_RUBRIC_MAX_ITERATIONS must be an integer") from exc
    if not 1 <= value <= 20:
        raise ValueError("CURATOR_RUBRIC_MAX_ITERATIONS must be between 1 and 20")
    return value


def _load_selected_rules() -> list[tuple[str, str]]:
    from services.api.models.rule import collect_rules_from_db

    rules = collect_rules_from_db(RULE_AGENT, project=str(REPO_ROOT))
    if not rules:
        raise ValueError(
            f"Improve graph found no enabled harness rules assigned to agent "
            f"'{RULE_AGENT}'. Assign rules to the '{RULE_AGENT}' agent in the harness."
        )
    return rules


def _within_lookback(row: dict, days: int) -> bool:
    raw = row.get("updated_at") or row.get("created_at")
    if not raw:
        return False
    try:
        ts = datetime.fromisoformat(str(raw))
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts >= datetime.now(timezone.utc) - timedelta(days=days)


def _recent_plan_entries(project: str | None, days: int) -> list[tuple[str, str]]:
    from services.api.models.plan import get_plan, list_plans

    summaries, _ = list_plans(project=project, limit=100)
    entries = []
    for summary in summaries:
        if not _within_lookback(summary, days):
            continue
        plan = get_plan(summary["id"])
        entries.append((str(plan["id"]), f"# {plan['title']}\n{plan['body']}"))
    return entries


def _recent_memory_entries(project: str | None, days: int) -> list[tuple[str, str]]:
    from services.memory.db import list_memories

    rows = list_memories(repo=project, sort="created_at_desc", limit=500)
    return [(str(r["id"]), r["content"]) for r in rows if _within_lookback(r, days)]


async def _digest(model, source: str, entries: list[tuple[str, str]]) -> str:
    """Map-reduce a full, untruncated corpus into a findings digest."""
    if not entries:
        return f"No {source} entries in the lookback window."

    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for entry_id, text in entries:
        block = f"[{source} {entry_id}]\n{text}"
        if current and size + len(block) > CHUNK_CHAR_BUDGET:
            chunks.append("\n\n".join(current))
            current, size = [], 0
        current.append(block)
        size += len(block)
    if current:
        chunks.append("\n\n".join(current))

    map_prompt = SystemMessage(
        content=(
            f"You curate {source}s for an agentic coding harness. Extract recurring patterns, "
            "pain points, conventions, and improvement opportunities relevant to harness rules, "
            "skills, hooks, or background jobs. For each finding give a one-line theme, the "
            f"source references in [{source} <id>] form, and a 1-2 sentence summary. Report only "
            "what is actually present; say so if nothing stands out."
        )
    )
    digests = []
    for chunk in chunks:
        response = await model.ainvoke([map_prompt, HumanMessage(content=chunk)])
        digests.append(extract_text(response))
    if len(digests) == 1:
        return digests[0]

    reduce_prompt = SystemMessage(
        content=(
            f"Merge these partial {source} digests into one deduplicated findings list, "
            "preserving the source references."
        )
    )
    response = await model.ainvoke(
        [reduce_prompt, HumanMessage(content="\n\n---\n\n".join(digests))]
    )
    return extract_text(response)


def _inventory_summary(project: str | None) -> str:
    from services.api.models.shared.harness import list_items_summary
    from services.jobs.models.job import list_jobs

    lines = []
    for item_type in ("rule", "skill", "hook"):
        rows = list_items_summary(item_type, project=project)
        names = ", ".join(
            f"{r['name']}{'' if r['enabled'] else ' (disabled)'}" for r in rows
        )
        lines.append(f"{item_type}s: {names or '(none)'}")
    jobs, _ = list_jobs(limit=200)
    job_names = ", ".join(f"{j['name']} ({j['schedule_config']})" for j in jobs)
    lines.append(f"jobs: {job_names or '(none)'}")
    return "\n".join(lines)


def _recent_titles_block() -> str:
    from services.api.models.proposal import recent_proposal_titles

    titles = recent_proposal_titles()
    if not titles:
        return "(none)"
    return "\n".join(f"- [{status}] {title}" for title, status in titles)


def _raise_contract_error(status: str, explanation: str) -> None:
    from services.graphs.runtime import GraphContractError

    if status in TERMINAL_FAILURES:
        raise GraphContractError(f"Improve rubric did not pass: {status}. {explanation}")
    raise GraphContractError(f"Improve graph contract failed: {status}. {explanation}")

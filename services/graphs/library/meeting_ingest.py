"""Import all configured meeting connections, or one optional named source."""

from __future__ import annotations

import asyncio
import json
from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from services.meetings.enrichment import (
    DigestionRun,
    GRAPH_WORK_SECONDS,
    IMPORT_SECONDS,
)
from services.meetings.processing import graph_outcome
from services.meetings.action_item_run import ActionItemRun

INPUT_SCHEMA = {"source": "string?", "digest": "boolean?"}


def validate_input_values(inputs: dict) -> None:
    if "meeting_id" in inputs:
        raise ValueError(
            "meeting_ingest no longer supports meeting_id: automatic participant identification was removed"
        )


class State(TypedDict):
    source: NotRequired[str]
    digest: NotRequired[bool]
    result: dict
    digestion: DigestionRun
    action_item_run: ActionItemRun


async def _sync_summaries(state: State) -> dict:
    from services.meetings.service import sync_sources

    if await state["digestion"].prepare_manual():
        return {
            "result": {
                "outcome": "completed",
                "summary_outcome": "skipped",
                "transcript": state["digestion"].transcript_report,
            }
        }
    result = await sync_sources(
        state.get("source"), run_budget_seconds=IMPORT_SECONDS, raise_on_failure=False
    )
    result["summary_outcome"] = result["outcome"]
    await state["digestion"].prepare()
    result["transcript"] = state["digestion"].transcript_report
    return {"result": result}


async def _generate_memories(state: State) -> dict:
    await state["digestion"].generate_memories()
    return {"result": {**state["result"], "memories": state["digestion"].memory_report}}


def _next_stage(state: State) -> str:
    return (
        "generate_memories"
        if state["digestion"].has_memory_work()
        else "generate_action_items"
    )


async def _generate_action_items(state: State) -> dict:
    if not state.get("digest", True):
        return {"result": {**state["result"], "action_items": {"outcome": "disabled"}}}
    run = state["action_item_run"]
    await run.prepare()
    await run.generate_candidates()
    return {"result": {**state["result"], "action_items": run.report}}


async def _filter_action_items(state: State) -> dict:
    if state.get("digest", True):
        await state["action_item_run"].filter_candidates()
        return {
            "result": {
                **state["result"],
                "action_items": state["action_item_run"].report,
            }
        }
    return {}


class MeetingGraph:
    def __init__(self, graph) -> None:
        self.graph = graph

    def get_graph(self, *args, **kwargs):
        return self.graph.get_graph(*args, **kwargs)

    async def ainvoke(self, inputs: dict):
        from services.meetings.service import MeetingSyncError

        validate_input_values(inputs)
        state = {}
        try:
            async with DigestionRun(
                inputs.get("source"), digest=inputs.get("digest", True)
            ) as run:
                async with ActionItemRun(
                    inputs.get("source"), deadline=run.deadline
                ) as action_items:
                    async with asyncio.timeout(GRAPH_WORK_SECONDS):
                        state = await self.graph.ainvoke(
                            {
                                **inputs,
                                "digestion": run,
                                "action_item_run": action_items,
                            }
                        )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise MeetingSyncError(
                json.dumps({"outcome": "failed", "error_type": type(error).__name__})
            ) from None
        result = graph_outcome(
            state["result"],
            [
                state["result"].get(key, {})
                for key in ("transcript", "memories", "action_items")
            ],
        )
        state["result"] = result
        if result.get("outcome") == "failed":
            raise MeetingSyncError(json.dumps(result, sort_keys=True)) from None
        return state


def build_graph():
    graph = StateGraph(State)
    graph.add_node("sync_summaries", _sync_summaries)
    graph.add_node("generate_memories", _generate_memories)
    graph.add_node("generate_action_items", _generate_action_items)
    graph.add_node("filter_action_items", _filter_action_items)
    graph.add_edge(START, "sync_summaries")
    graph.add_conditional_edges(
        "sync_summaries",
        _next_stage,
        {
            "generate_memories": "generate_memories",
            "generate_action_items": "generate_action_items",
        },
    )
    graph.add_edge("generate_memories", "generate_action_items")
    graph.add_edge("generate_action_items", "filter_action_items")
    graph.add_edge("filter_action_items", END)
    return MeetingGraph(graph.compile())

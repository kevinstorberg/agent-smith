"""Import all configured meeting connections, or one optional named source."""
from __future__ import annotations

import asyncio
import json
from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from services.meetings.enrichment import DigestionRun, GRAPH_WORK_SECONDS, IMPORT_SECONDS

INPUT_SCHEMA = {"source": "string?", "digest": "boolean?"}


class State(TypedDict):
    source: NotRequired[str]
    digest: NotRequired[bool]
    result: dict
    digestion: DigestionRun


async def _sync_summaries(state: State) -> dict:
    from services.meetings.service import sync_sources

    result = await sync_sources(state.get("source"), run_budget_seconds=IMPORT_SECONDS, raise_on_failure=False)
    await state["digestion"].prepare()
    result["transcript"] = state["digestion"].transcript_report
    return {"result": result}


async def _generate_memories(state: State) -> dict:
    await state["digestion"].generate_memories()
    return {"result": {**state["result"], "memories": state["digestion"].memory_report}}


class MeetingGraph:
    def __init__(self, graph) -> None:
        self.graph = graph

    def get_graph(self, *args, **kwargs):
        return self.graph.get_graph(*args, **kwargs)

    async def ainvoke(self, inputs: dict):
        from services.meetings.service import MeetingSyncError

        state = {}
        try:
            async with DigestionRun(inputs.get("source"), digest=inputs.get("digest", True)) as run:
                async with asyncio.timeout(GRAPH_WORK_SECONDS):
                    state = await self.graph.ainvoke({**inputs, "digestion": run})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise MeetingSyncError(json.dumps({"outcome": "failed", "error_type": type(error).__name__})) from None
        result = state["result"]
        if result.get("outcome") == "failed" or any(result.get(key, {}).get("outcome") == "failed" for key in ("transcript", "memories")):
            raise MeetingSyncError(json.dumps(result, sort_keys=True)) from None
        return state


def build_graph():
    graph = StateGraph(State)
    graph.add_node("sync_summaries", _sync_summaries)
    graph.add_node("generate_memories", _generate_memories)
    graph.add_edge(START, "sync_summaries")
    graph.add_conditional_edges("sync_summaries", lambda state: "generate_memories" if state["digestion"].has_memory_work() else END)
    graph.add_edge("generate_memories", END)
    return MeetingGraph(graph.compile())

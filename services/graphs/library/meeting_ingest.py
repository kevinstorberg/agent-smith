"""Import all configured meeting connections, or one optional named source."""
from __future__ import annotations

import json
from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

INPUT_SCHEMA = {"source": "string?"}


class State(TypedDict):
    source: NotRequired[str]
    result: dict


async def _sync_summaries(state: State) -> dict:
    from services.meetings.digestion import capture_transcripts
    from services.meetings.service import MeetingSyncError, sync_sources

    result = await sync_sources(state.get("source"), run_budget_seconds=120, raise_on_failure=False)
    result["transcript"] = await capture_transcripts(state.get("source"))
    if result.get("outcome") == "failed" or result["transcript"]["outcome"] == "failed":
        raise MeetingSyncError(json.dumps(result, sort_keys=True)) from None
    return {"result": result}


def build_graph():
    graph = StateGraph(State)
    graph.add_node("sync_summaries", _sync_summaries)
    graph.add_edge(START, "sync_summaries")
    graph.add_edge("sync_summaries", END)
    return graph.compile()

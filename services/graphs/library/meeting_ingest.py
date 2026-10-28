"""Import all configured meeting connections, or one optional named source."""
from __future__ import annotations

from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

INPUT_SCHEMA = {"source": "string?"}


class State(TypedDict):
    source: NotRequired[str]
    result: dict


async def _sync_summaries(state: State) -> dict:
    from services.meetings.service import sync_sources

    return {"result": await sync_sources(state.get("source"))}


def build_graph():
    graph = StateGraph(State)
    graph.add_node("sync_summaries", _sync_summaries)
    graph.add_edge(START, "sync_summaries")
    graph.add_edge("sync_summaries", END)
    return graph.compile()

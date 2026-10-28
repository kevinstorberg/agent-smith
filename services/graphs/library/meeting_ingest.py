"""Import meeting summaries as context using a configured note provider."""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

INPUT_SCHEMA = {"source": "string"}


class State(TypedDict):
    source: str
    result: dict


async def _sync_summaries(state: State) -> dict:
    from services.meetings.service import sync_source

    return {"result": await sync_source(state["source"])}


def build_graph():
    graph = StateGraph(State)
    graph.add_node("sync_summaries", _sync_summaries)
    graph.add_edge(START, "sync_summaries")
    graph.add_edge("sync_summaries", END)
    return graph.compile()

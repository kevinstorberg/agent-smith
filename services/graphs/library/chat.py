"""Chat: returns a read-only snapshot of one Chat Room."""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from services.chat.service import snapshot

INPUT_SCHEMA = {"room_id": "integer"}


class State(TypedDict):
    room_id: int
    result: dict[str, Any]


def _read_snapshot(state: State) -> State:
    return {"room_id": state["room_id"], "result": snapshot(state["room_id"])}


def build_graph():
    graph = StateGraph(State)
    graph.add_node("snapshot", _read_snapshot)
    graph.add_edge(START, "snapshot")
    graph.add_edge("snapshot", END)
    return graph.compile()

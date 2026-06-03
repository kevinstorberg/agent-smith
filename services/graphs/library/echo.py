"""Echo: returns the input text verbatim. Tracer-bullet graph with no LLM call."""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

INPUT_SCHEMA = {"text": "string"}


class State(TypedDict):
    text: str
    result: str


def _echo(state: State) -> State:
    return {"text": state["text"], "result": state["text"]}


def build_graph():
    g = StateGraph(State)
    g.add_node("echo", _echo)
    g.add_edge(START, "echo")
    g.add_edge("echo", END)
    return g.compile()

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
    graph = StateGraph(State)
    graph.add_node("echo", _echo)
    graph.add_edge(START, "echo")
    graph.add_edge("echo", END)
    return graph.compile()

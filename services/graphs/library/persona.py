"""Build cumulative personas from saved context, independently of meeting memories."""
from __future__ import annotations

import asyncio
import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from services.meetings.processing import GRAPH_WORK_SECONDS, graph_outcome
from services.personas.service import PersonaRun

INPUT_SCHEMA = {"source": "string?"}


class PersonaProcessingError(RuntimeError):
    pass


class State(TypedDict):
    run: PersonaRun
    result: dict


async def _load_context(state: State) -> dict:
    await state["run"].prepare()
    return {}


async def _update_personas(state: State) -> dict:
    run = state["run"]
    await run.build_profiles()
    return {"result": graph_outcome({"outcome": "completed", "profiles": run.profile_report}, [run.profile_report])}


class PersonaGraph:
    def __init__(self, graph):
        self.graph = graph

    def get_graph(self, *args, **kwargs):
        return self.graph.get_graph(*args, **kwargs)

    async def ainvoke(self, inputs: dict) -> dict:
        try:
            async with PersonaRun(inputs.get("source")) as run:
                async with asyncio.timeout(GRAPH_WORK_SECONDS):
                    state = await self.graph.ainvoke({"run": run})
                    result = state["result"]
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise PersonaProcessingError(json.dumps({"outcome": "failed", "error_type": type(error).__name__})) from None
        if result["outcome"] == "failed":
            raise PersonaProcessingError(json.dumps(result, sort_keys=True)) from None
        return {"result": result}


def build_graph():
    graph = StateGraph(State)
    graph.add_node("load_context", _load_context)
    graph.add_node("update_personas", _update_personas)
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "update_personas")
    graph.add_edge("update_personas", END)
    return PersonaGraph(graph.compile())

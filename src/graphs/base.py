from dataclasses import dataclass
from inspect import isawaitable
from typing import Any, Protocol, runtime_checkable

from langgraph.graph import StateGraph

from config.loader import load_graph_config
from config.models import GraphConfig
from config.prompts.loader import load_prompt
from src.agents.base import create_react_agent_graph
from src.agents.llm import build_llm
from src.graphs.checkpointing import create_checkpointer
from src.models.state import BaseState
from src.tools import load_tools
from src.tools.context import ToolContext


@runtime_checkable
class GraphFactory(Protocol):
    def build(self, graph_name: str, **kwargs) -> object: ...


@dataclass(frozen=True)
class GraphRuntime:
    graph: Any
    config: GraphConfig
    recursion_limit: int

    def run_config(self, *, thread_id: str | None = None) -> dict[str, Any]:
        config: dict[str, Any] = {"recursion_limit": self.recursion_limit}
        if thread_id:
            config["configurable"] = {"thread_id": thread_id}
        return config

    async def ainvoke(self, state: dict[str, Any], *, thread_id: str | None = None) -> dict[str, Any]:
        return await self.graph.ainvoke(state, config=self.run_config(thread_id=thread_id))

    async def astream_events(self, state: dict[str, Any], *, thread_id: str | None = None):
        events = self.graph.astream_events(
            state,
            config=self.run_config(thread_id=thread_id),
            version="v2",
        )
        if isawaitable(events):
            events = await events

        if hasattr(events, "__aiter__"):
            async for event in events:
                yield event
            return

        for event in events:
            yield event


def build_graph_runtime(
    graph_name: str,
    *,
    model_override: str | None = None,
    scope: dict | None = None,
) -> GraphRuntime:
    config = load_graph_config(graph_name, require_file=True)
    runtime_kind = config.runtime.kind.lower()
    if runtime_kind != "react":
        raise ValueError(f"Unknown graph runtime kind: {config.runtime.kind!r}")

    context = ToolContext.from_graph_config(config, scope=scope)
    tools = load_tools(config.tools, context)
    llm = build_llm(model=model_override, config=config.llm)
    checkpointer = create_checkpointer(config)
    system_prompt = load_prompt(config.runtime.prompt) if config.runtime.prompt else ""
    graph = create_react_agent_graph(
        llm,
        tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer,
        name=config.name,
    )
    return GraphRuntime(graph=graph, config=config, recursion_limit=config.runtime.recursion_limit)


def build_graph_from_config(
    graph_name: str,
    *,
    model_override: str | None = None,
    scope: dict | None = None,
):
    return build_graph_runtime(graph_name, model_override=model_override, scope=scope).graph


def build_config_summary_graph(graph_name: str, *, model_override: str | None = None):
    config = load_graph_config(graph_name)

    graph = StateGraph(BaseState)
    graph.add_node("process", lambda state: _with_graph_config(state, config, model_override))
    graph.set_entry_point("process")
    graph.set_finish_point("process")
    return graph.compile()


def _graph_config_summary(config: GraphConfig, model_override: str | None) -> dict[str, Any]:
    return {
        "name": config.name,
        "llm": {
            "provider": config.llm.provider,
            "model": model_override or config.llm.model,
            "max_tokens": config.llm.max_tokens,
        },
        "tools": list(config.tools),
        "runtime": {
            "kind": config.runtime.kind,
            "prompt": config.runtime.prompt,
            "recursion_limit": config.runtime.recursion_limit,
        },
        "checkpoint": {"backend": config.checkpoint.backend},
        "checkpointing": config.checkpointing,
        "validation": dict(config.validation),
    }


def _with_graph_config(state: BaseState, config: GraphConfig, model_override: str | None) -> BaseState:
    return {
        **state,
        "graph_config": _graph_config_summary(config, model_override),
    }

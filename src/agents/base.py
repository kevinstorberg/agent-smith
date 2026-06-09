from typing import Any

from langchain_core.tools import BaseTool


def _resolve_create_agent():
    from langchain.agents import create_agent

    return create_agent


def create_react_agent_graph(
    llm: Any,
    tools: list[BaseTool],
    *,
    system_prompt: str = "",
    checkpointer: Any | None = None,
    name: str | None = None,
):
    kwargs: dict[str, Any] = {}
    if system_prompt:
        kwargs["system_prompt"] = system_prompt
    if checkpointer is not None:
        kwargs["checkpointer"] = checkpointer
    if name:
        kwargs["name"] = name

    create_agent = _resolve_create_agent()
    return create_agent(llm, tools, **kwargs)


async def build_react_agent(
    llm: Any,
    tools: list[BaseTool],
    *,
    system_prompt: str = "",
    recursion_limit: int = 25,
    checkpointer: Any | None = None,
):
    return create_react_agent_graph(llm, tools, system_prompt=system_prompt, checkpointer=checkpointer)

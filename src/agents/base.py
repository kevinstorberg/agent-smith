from typing import Any

from langchain_core.tools import BaseTool


def _resolve_create_react_agent():
    try:
        from langgraph.prebuilt import create_react_agent
    except ImportError:
        from langgraph.prebuilt.chat_agent_executor import create_react_agent

    return create_react_agent


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
        kwargs["prompt"] = system_prompt
    if checkpointer is not None:
        kwargs["checkpointer"] = checkpointer
    if name:
        kwargs["name"] = name

    create_react_agent = _resolve_create_react_agent()
    return create_react_agent(llm, tools, **kwargs)


async def build_react_agent(
    llm: Any,
    tools: list[BaseTool],
    *,
    system_prompt: str = "",
    recursion_limit: int = 25,
    checkpointer: Any | None = None,
):
    return create_react_agent_graph(llm, tools, system_prompt=system_prompt, checkpointer=checkpointer)

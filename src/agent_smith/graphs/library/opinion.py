"""Opinion: returns a critical opinion on a proposed plan or architecture."""

from __future__ import annotations

from typing import TypedDict

from langchain.chat_models import init_chat_model
from langgraph.graph import END, START, StateGraph

MODEL = "gpt-4o-mini"
PROVIDER = "openai"
INPUT_SCHEMA = {"proposal": "string"}

_SYSTEM_PROMPT = (
    "You are a senior engineer giving a candid second opinion on a proposed plan or "
    "architecture. Be specific and honest. Cover, in this order:\n"
    "  1. What you think is sound about the proposal.\n"
    "  2. The single biggest risk or weakness you see.\n"
    "  3. One or two concrete simplifications or alternatives worth considering.\n"
    "  4. Any unstated assumptions the author should verify.\n"
    "Keep the response tight - prioritize signal over breadth. Do not flatter; do not hedge."
)


class State(TypedDict):
    proposal: str
    result: str


def build_graph():
    llm = init_chat_model(model=MODEL, model_provider=PROVIDER)

    async def _opine(state: State) -> State:
        message = await llm.ainvoke(
            [
                ("system", _SYSTEM_PROMPT),
                ("user", state["proposal"]),
            ]
        )
        return {"proposal": state["proposal"], "result": _extract_text(message)}

    graph = StateGraph(State)
    graph.add_node("opine", _opine)
    graph.add_edge(START, "opine")
    graph.add_edge("opine", END)
    return graph.compile()


def _extract_text(message) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [part.get("text", "") if isinstance(part, dict) else str(part) for part in content]
        return "".join(parts)
    return str(content)

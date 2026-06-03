"""Summarize: condenses input text into 2-3 concise sentences via an LLM."""
from __future__ import annotations

from typing import TypedDict

from langchain.chat_models import init_chat_model
from langgraph.graph import END, START, StateGraph

MODEL = "gpt-4o-mini"
PROVIDER = "openai"
INPUT_SCHEMA = {"text": "string"}

_SYSTEM_PROMPT = "Summarize the user's text in 2-3 concise sentences. Return only the summary."


class State(TypedDict):
    text: str
    result: str


def build_graph():
    llm = init_chat_model(model=MODEL, model_provider=PROVIDER)

    async def _summarize(state: State) -> State:
        msg = await llm.ainvoke([
            ("system", _SYSTEM_PROMPT),
            ("user", state["text"]),
        ])
        return {"text": state["text"], "result": _extract_text(msg)}

    g = StateGraph(State)
    g.add_node("summarize", _summarize)
    g.add_edge(START, "summarize")
    g.add_edge("summarize", END)
    return g.compile()


def _extract_text(msg) -> str:
    content = getattr(msg, "content", msg)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in content]
        return "".join(parts)
    return str(content)

"""Review_diff: reads a unified diff file and produces structured review notes."""
from __future__ import annotations

from typing import TypedDict

from langchain.chat_models import init_chat_model
from langgraph.graph import END, START, StateGraph

from services.graphs.tools.file_tools import read_file

MODEL = "gpt-4o-mini"
PROVIDER = "openai"
INPUT_SCHEMA = {"diff_path": "string"}

_REVIEW_SYSTEM_PROMPT = (
    "You are a senior code reviewer. Given a unified diff, return JSON with two keys:\n"
    "  summary: a 1-2 sentence summary of what the diff does\n"
    "  observations: a list of strings, each a concrete observation or concern\n"
    "Return ONLY the JSON object, no surrounding markdown."
)


class State(TypedDict):
    diff_path: str
    diff_content: str
    result: str


def build_graph():
    llm = init_chat_model(model=MODEL, model_provider=PROVIDER)

    def _load(state: State) -> State:
        content = read_file.invoke({"path": state["diff_path"]})
        return {"diff_path": state["diff_path"], "diff_content": content, "result": ""}

    async def _review(state: State) -> State:
        msg = await llm.ainvoke([
            ("system", _REVIEW_SYSTEM_PROMPT),
            ("user", f"Review this diff:\n\n{state['diff_content']}"),
        ])
        return {
            "diff_path": state["diff_path"],
            "diff_content": state["diff_content"],
            "result": _extract_text(msg),
        }

    g = StateGraph(State)
    g.add_node("load", _load)
    g.add_node("review", _review)
    g.add_edge(START, "load")
    g.add_edge("load", "review")
    g.add_edge("review", END)
    return g.compile()


def _extract_text(msg) -> str:
    content = getattr(msg, "content", msg)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in content]
        return "".join(parts)
    return str(content)

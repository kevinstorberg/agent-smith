"""Text extraction from LangChain/DeepAgents message and result shapes."""
from __future__ import annotations

from typing import Any


def extract_text(msg: Any) -> str:
    text = getattr(msg, "text", None)
    if isinstance(text, str):
        return text
    if callable(text):
        value = text()
        if isinstance(value, str):
            return value

    content = getattr(msg, "content", msg)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in content]
        return "".join(parts)
    return str(content)


def extract_result_text(result: Any) -> str:
    """The final text of an agent invocation result (last message wins)."""
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list) and messages:
            return extract_text(messages[-1])
        output = result.get("output") or result.get("result")
        if output is not None:
            return extract_text(output)
    return extract_text(result)

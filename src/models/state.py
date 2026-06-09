from typing import Annotated, Any, TypedDict

from langgraph.graph import add_messages


def add_messages_reducer(existing: list, new: list) -> list:
    """Simple list concatenation reducer.

    Kept for backward compatibility. Prefer langgraph.graph.add_messages
    for production graphs — it handles deduplication and message types.
    """
    return existing + new


class BaseState(TypedDict, total=False):
    """Base state for all LangGraph graphs.

    Uses LangGraph's built-in add_messages reducer to properly
    accumulate messages across node invocations.
    """

    messages: Annotated[list, add_messages]
    graph_config: dict[str, Any]

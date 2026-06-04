from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()

import logging  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

from services.graphs.runtime import build_tool_description, dispatch, scan_library  # noqa: E402

logger = logging.getLogger(__name__)

_registry = scan_library()
logger.info(
    "graphs: registered %d types (%s)",
    len(_registry),
    ", ".join(sorted(_registry)) or "none",
)

mcp = FastMCP("graphs - run hardcoded LangGraph workflows")


@mcp.tool(description=build_tool_description(_registry))
async def run_graph(type: str, inputs: dict) -> str:
    return await dispatch(type, inputs)

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Any, Callable

from lib.agent_smith_core.paths import get_module_dir
from src.tools.context import ToolContext

logger = logging.getLogger(__name__)

TOOL_FACTORY: dict[str, Callable[[ToolContext], Any]] = {}


def register_tool(name: str):
    """Register a tool factory function.

    Args:
        name: Unique name for the tool

    Returns:
        Decorator that registers the factory function
    """

    def decorator(fn: Callable[[ToolContext], Any]):
        TOOL_FACTORY[name] = fn
        return fn

    return decorator


def _should_auto_import(module_name: str) -> bool:
    return not module_name.startswith("_") and module_name != "context"


def _auto_import_tools(package_name: str = __name__, tools_dir: Path | None = None) -> None:
    """Auto-import all tool modules to trigger @register_tool decorators."""
    resolved_tools_dir = tools_dir or get_module_dir(__file__)

    for _, module_name, _ in pkgutil.iter_modules([str(resolved_tools_dir)]):
        if not _should_auto_import(module_name):
            continue
        try:
            importlib.import_module(f"{package_name}.{module_name}")
            logger.debug(f"Auto-imported tool module: {module_name}")
        except ImportError as e:
            logger.warning(f"Failed to import tool module {module_name}: {e}")


def load_tools(tool_names: list[str], context: ToolContext) -> list[Any]:
    """Load tools by name using registered factories.

    Args:
        tool_names: List of tool names to load
        context: Tool context with config and settings

    Returns:
        List of instantiated tool objects (None tools filtered out)
    """
    tools = []
    for name in tool_names:
        if name not in TOOL_FACTORY:
            available = ", ".join(sorted(TOOL_FACTORY.keys()))
            raise ValueError(f"Unknown tool '{name}'. Available: {available}")
        tool = TOOL_FACTORY[name](context)
        if tool is not None:
            tools.append(tool)
    return tools


def discover_tools() -> dict[str, Callable[[ToolContext], Any]]:
    _auto_import_tools()
    return dict(TOOL_FACTORY)


# Call auto-import after all functions are defined
_auto_import_tools()

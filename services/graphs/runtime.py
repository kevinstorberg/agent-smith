from __future__ import annotations

import importlib
import json
import logging
import pkgutil
from types import ModuleType
from typing import Any

logger = logging.getLogger(__name__)


class GraphContractError(RuntimeError):
    pass


_PRIMITIVE_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


def scan_library() -> dict[str, ModuleType]:
    """Return a name -> module map for every valid graph in services.graphs.library."""
    import services.graphs.library as lib_pkg

    registry: dict[str, ModuleType] = {}
    for info in pkgutil.iter_modules(lib_pkg.__path__):
        if info.ispkg or info.name.startswith("_"):
            continue
        full_name = f"{lib_pkg.__name__}.{info.name}"
        try:
            mod = importlib.import_module(full_name)
        except Exception as e:
            logger.warning("graphs: skipping %s: import failed: %s", info.name, e)
            continue
        if not hasattr(mod, "INPUT_SCHEMA") or not isinstance(mod.INPUT_SCHEMA, dict):
            logger.warning("graphs: skipping %s: missing or invalid INPUT_SCHEMA", info.name)
            continue
        if not hasattr(mod, "build_graph") or not callable(mod.build_graph):
            logger.warning("graphs: skipping %s: missing or non-callable build_graph", info.name)
            continue
        registry[info.name] = mod
    return registry


def build_tool_description(registry: dict[str, ModuleType] | None = None) -> str:
    """Build the run_graph tool description from the current library scan."""
    if registry is None:
        registry = scan_library()
    if not registry:
        return "Run a hardcoded LangGraph workflow by type. No graphs are currently registered."

    lines = [
        "Run a hardcoded LangGraph workflow identified by `type` with the given `inputs` dict.",
        "",
        "Available types:",
    ]
    for name in sorted(registry):
        mod = registry[name]
        schema = ", ".join(f"{k}: {v}" for k, v in mod.INPUT_SCHEMA.items())
        doc = (mod.__doc__ or "").strip().split("\n")[0]
        suffix = f" — {doc}" if doc else ""
        lines.append(f"- {name} (inputs: {{{schema}}}){suffix}")
    return "\n".join(lines)


def validate_inputs(
    graph_type: str, inputs: dict[str, Any], registry: dict[str, ModuleType] | None = None
) -> None:
    """Validate inputs against a graph's INPUT_SCHEMA without running it.

    Shared by ``dispatch`` and job-creation validation so a graph job with bad
    inputs is rejected when it is created, not at its first scheduled run.
    Raises KeyError for an unknown graph type, ValueError for bad inputs.
    """
    if registry is None:
        registry = scan_library()
    if graph_type not in registry:
        raise KeyError(f"unknown graph type: '{graph_type}'")

    mod = registry[graph_type]
    for field, type_name in mod.INPUT_SCHEMA.items():
        py_type = _PRIMITIVE_TYPES.get(type_name)
        if py_type is None:
            raise ValueError(
                f"graph '{graph_type}' has unsupported input type '{type_name}' for field '{field}'"
            )
        if field not in inputs or not isinstance(inputs[field], py_type):
            raise ValueError(
                f"graph '{graph_type}' input '{field}' missing or wrong type"
            )


async def dispatch(graph_type: str, inputs: dict[str, Any]) -> str:
    """Validate inputs, run the graph, and return a string-serialized result."""
    assert isinstance(graph_type, str) and graph_type, "graph type must be a non-empty string"
    assert isinstance(inputs, dict), "inputs must be a dict"

    registry = scan_library()
    validate_inputs(graph_type, inputs, registry)

    graph = registry[graph_type].build_graph()
    result = await graph.ainvoke(inputs)
    if not result:
        raise GraphContractError(f"graph '{graph_type}' returned no result")

    out = result.get("result", result) if isinstance(result, dict) else result
    if isinstance(out, str):
        return out
    return json.dumps(out, default=str)

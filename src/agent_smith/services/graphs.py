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


PRIMITIVE_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


class AgentSmithGraphService:
    def scan_library(self) -> dict[str, ModuleType]:
        import src.agent_smith.graphs.library as graph_library

        registry: dict[str, ModuleType] = {}
        for info in pkgutil.iter_modules(graph_library.__path__):
            if info.ispkg or info.name.startswith("_"):
                continue
            full_name = f"{graph_library.__name__}.{info.name}"
            try:
                module = importlib.import_module(full_name)
            except Exception as exc:
                logger.warning("Agent Smith graph skipped %s: import failed: %s", info.name, exc)
                continue
            if not hasattr(module, "INPUT_SCHEMA") or not isinstance(module.INPUT_SCHEMA, dict):
                logger.warning("Agent Smith graph skipped %s: missing or invalid INPUT_SCHEMA", info.name)
                continue
            if not hasattr(module, "build_graph") or not callable(module.build_graph):
                logger.warning("Agent Smith graph skipped %s: missing callable build_graph", info.name)
                continue
            registry[info.name] = module
        return registry

    def build_tool_description(self, registry: dict[str, ModuleType] | None = None) -> str:
        registry = registry or self.scan_library()
        if not registry:
            return "Run a hardcoded LangGraph workflow by type. No graphs are currently registered."

        lines = [
            "Run a hardcoded LangGraph workflow identified by `type` with the given `inputs` dict.",
            "",
            "Available types:",
        ]
        for name in sorted(registry):
            module = registry[name]
            schema = ", ".join(f"{key}: {value}" for key, value in module.INPUT_SCHEMA.items())
            doc = (module.__doc__ or "").strip().split("\n")[0]
            suffix = f" - {doc}" if doc else ""
            lines.append(f"- {name} (inputs: {{{schema}}}){suffix}")
        return "\n".join(lines)

    async def dispatch(self, graph_type: str, inputs: dict[str, Any]) -> str:
        if not isinstance(graph_type, str) or not graph_type:
            raise ValueError("graph type must be a non-empty string")
        if not isinstance(inputs, dict):
            raise ValueError("inputs must be a dict")

        registry = self.scan_library()
        if graph_type not in registry:
            raise KeyError(f"unknown graph type: '{graph_type}'")

        module = registry[graph_type]
        for field, type_name in module.INPUT_SCHEMA.items():
            python_type = PRIMITIVE_TYPES.get(type_name)
            if python_type is None:
                raise ValueError(f"graph '{graph_type}' has unsupported input type '{type_name}' for field '{field}'")
            if field not in inputs or not isinstance(inputs[field], python_type):
                raise ValueError(f"graph '{graph_type}' input '{field}' missing or wrong type")

        graph = module.build_graph()
        result = await graph.ainvoke(inputs)
        if not result:
            raise GraphContractError(f"graph '{graph_type}' returned no result")

        output = result.get("result", result) if isinstance(result, dict) else result
        if isinstance(output, str):
            return output
        return json.dumps(output, default=str)


def get_graph_service() -> AgentSmithGraphService:
    return AgentSmithGraphService()

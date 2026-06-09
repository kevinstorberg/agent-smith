# Tool Development Guide

Tools are LangChain callables that graph builders can load by name. Cairn keeps
tool discovery simple: public modules in `src/tools/` are imported when
`src.tools` is imported, and `@register_tool(...)` adds factories to the registry.

## Create A Tool

```python
# src/tools/lookup_record.py
from langchain_core.tools import StructuredTool

from src.tools import register_tool
from src.tools.context import ToolContext


@register_tool("lookup_record")
def create_lookup_record_tool(context: ToolContext):
    async def lookup_record(record_id: str) -> dict:
        """Look up a record by ID."""
        return {"id": record_id}

    return StructuredTool.from_function(
        coroutine=lookup_record,
        name="lookup_record",
        description="Look up a record by ID.",
    )
```

Rules:

- Keep examples and scratch modules out of `src/tools/`; public modules there are
  production auto-discovered.
- Prefix private helper modules with `_`.
- Use factory names that make the registered tool obvious.
- Return `None` only when a tool is intentionally disabled for the supplied
  `ToolContext`.

## Tool Context

`ToolContext` carries graph metadata and optional scope. The field definitions live
in [src/tools/context.py](../src/tools/context.py).

Typical graph usage:

```python
from config.loader import load_graph_config
from src.tools import load_tools
from src.tools.context import ToolContext

config = load_graph_config("workflow")
context = ToolContext.from_graph_config(config)
tools = load_tools(config.tools, context)
```

## Async Work

Cairn uses async database sessions and async web runtime. Tools that touch the
database, cache, memory, or network should expose async coroutines to LangChain
instead of forcing the event loop from a sync wrapper.

```python
from langchain_core.tools import StructuredTool

from db.connection import get_session_factory


async def lookup_record(record_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        ...


tool = StructuredTool.from_function(
    coroutine=lookup_record,
    name="lookup_record",
    description="Look up a record by ID.",
)
```

Do not call `asyncio.run()` or `loop.run_until_complete()` inside tools that may
run under FastAPI, Uvicorn, or LangGraph.

## Error Shape

Tool outputs are read by models and application code. Prefer small structured
responses over provider-specific exceptions:

```python
return {"ok": False, "error": "record_id is required"}
```

Raise only for programmer errors or broken assumptions that should stop execution.

## Testing

For registry tests, register a temporary tool name and remove it after the test.
For behavior tests, call the tool with a deterministic `ToolContext` and fake any
provider or database dependency at your application boundary.

```python
from src.tools import TOOL_FACTORY, load_tools, register_tool
from src.tools.context import ToolContext


def test_tool_registration():
    name = "_test_lookup"
    TOOL_FACTORY.pop(name, None)

    @register_tool(name)
    def create_tool(context: ToolContext):
        return "tool"

    try:
        assert load_tools([name], ToolContext()) == ["tool"]
    finally:
        TOOL_FACTORY.pop(name, None)
```

## Troubleshooting

- Unknown tool: check that the module is public, importable, and decorated.
- Tool missing from a graph: check `config/graphs/{name}.yaml`.
- Event loop already running: make the tool async and pass it as `coroutine`.
- Tool returns `None`: inspect conditional factory logic for the supplied context.

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.agent_smith.services.graphs import AgentSmithGraphService


class FakeGraph:
    async def ainvoke(self, inputs):
        return {"result": f"hello {inputs['name']}"}


def test_graph_tool_description_lists_registered_graph():
    module = SimpleNamespace(INPUT_SCHEMA={"name": "string"}, __doc__="Say hello.", build_graph=lambda: FakeGraph())
    service = AgentSmithGraphService()

    description = service.build_tool_description({"hello": module})

    assert "- hello (inputs: {name: string}) - Say hello." in description


@pytest.mark.asyncio
async def test_graph_dispatch_validates_inputs_and_returns_result(monkeypatch):
    module = SimpleNamespace(INPUT_SCHEMA={"name": "string"}, build_graph=lambda: FakeGraph())
    service = AgentSmithGraphService()
    monkeypatch.setattr(service, "scan_library", lambda: {"hello": module})

    result = await service.dispatch("hello", {"name": "Agent Smith"})

    assert result == "hello Agent Smith"


@pytest.mark.asyncio
async def test_graph_dispatch_rejects_unknown_graph(monkeypatch):
    service = AgentSmithGraphService()
    monkeypatch.setattr(service, "scan_library", lambda: {})

    with pytest.raises(KeyError, match="unknown graph type"):
        await service.dispatch("missing", {})

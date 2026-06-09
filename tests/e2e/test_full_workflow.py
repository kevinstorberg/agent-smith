"""
End-to-end integration test proving all layers work together.
Uses a generic 'Item' entity — zero domain coupling.
"""

import pytest
from starlette.testclient import TestClient

from cache.backends.memory import InMemoryCacheBackend
from cache.service import CacheService
from memory.backends.in_memory import InMemoryVectorBackend
from src.app import create_app
from src.evals.judge import build_criteria, extract_steps
from src.evals.results import EvalResult
from src.graphs.base import build_config_summary_graph
from src.policies.base import Permission, has_permission
from src.policies.roles import Role
from src.security.validation import validate_name, validate_uuid
from src.services.base import SERVICE_REGISTRY, create_service, register_service
from src.tools import TOOL_FACTORY, load_tools, register_tool
from src.tools.context import ToolContext


class TestE2EFullWorkflow:
    """Exercises every layer together in a single cohesive flow."""

    def test_health_endpoint(self):
        app = create_app()
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["app"] == "agent-smith"

    def test_security_validation(self):
        assert validate_name("test_item") == "test_item"
        assert validate_uuid("550e8400-e29b-41d4-a716-446655440000")

    def test_rbac_permissions(self):
        assert has_permission(Role.ADMIN, Permission.ADMIN) is True
        assert has_permission(Role.READONLY, Permission.WRITE) is False
        assert has_permission(Role.USER, Permission.READ) is True

    def test_graph_builds_and_invokes(self):
        graph = build_config_summary_graph("default")
        result = graph.invoke({"messages": ["hello"]})
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert result["messages"][0].content == "hello"

    def test_tool_registry_flow(self):
        factory_key = "_e2e_test_tool"
        if factory_key in TOOL_FACTORY:
            del TOOL_FACTORY[factory_key]

        @register_tool(factory_key)
        def create_test_tool(context: ToolContext):
            return "test_tool_instance"

        context = ToolContext(graph_name="e2e", tools=[factory_key])
        tools = load_tools([factory_key], context)
        assert tools == ["test_tool_instance"]

        del TOOL_FACTORY[factory_key]

    @pytest.mark.asyncio
    async def test_memory_store_and_search(self):
        backend = InMemoryVectorBackend()
        embedding = [0.1] * 384
        await backend.store("item-1", "Test item content", {"type": "item"}, embedding)
        results = await backend.search(embedding, limit=1)
        assert len(results) == 1
        assert results[0]["text"] == "Test item content"

    @pytest.mark.asyncio
    async def test_cache_roundtrip(self):
        backend = InMemoryCacheBackend()
        service = CacheService(backend=backend)
        await service.set("item:1", '{"name": "Test Item"}')
        cached = await service.get("item:1")
        assert cached == '{"name": "Test Item"}'
        second_read = await service.get("item:1")
        assert second_read == cached

    def test_websocket_message(self):
        app = create_app()
        client = TestClient(app)
        with client.websocket_connect("/ws/items") as ws:
            ws.send_json({"type": "message", "content": "item_created", "id": "item-1"})
            response = ws.receive_json()
            assert response["type"] == "message"
            assert response["content"] == "item_created"

    def test_evals_framework(self):
        criteria = build_criteria(prompt="Is the response accurate?", rule="Must cite sources")
        assert "accurate" in criteria
        assert "sources" in criteria

        steps = extract_steps("1. Check accuracy\n2. Verify sources")
        assert len(steps) == 2

        result = EvalResult(score=0.9, reasoning="Accurate with citations", criteria="accuracy")
        assert result.passed is True

    def test_service_registry(self):
        service_key = "_e2e_test_service"
        if service_key in SERVICE_REGISTRY:
            del SERVICE_REGISTRY[service_key]

        @register_service(service_key)
        class TestService:
            @classmethod
            def from_settings(cls, settings=None):
                return cls()

            async def health_check(self) -> bool:
                return True

            async def close(self) -> None:
                pass

        service = create_service(service_key)
        assert service is not None

        del SERVICE_REGISTRY[service_key]

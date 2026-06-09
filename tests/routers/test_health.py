import pytest
from httpx import ASGITransport, AsyncClient

from src.app import create_app


@pytest.fixture
async def client():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.integration
async def test_health_returns_200(client):
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.integration
async def test_health_status_ok(client):
    response = await client.get("/health")
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "cairn"


@pytest.mark.integration
async def test_health_includes_version(client):
    response = await client.get("/health")
    data = response.json()
    assert "version" in data
    assert isinstance(data["version"], str)

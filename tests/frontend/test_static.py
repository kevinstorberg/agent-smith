import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from config.models import FrontendConfig
from src.frontend.static import mount_frontend


@pytest.mark.unit
def test_frontend_static_mount_is_disabled_by_default(tmp_path):
    app = FastAPI()

    mounted = mount_frontend(app, FrontendConfig(), repo_root=tmp_path)

    assert mounted is False
    assert all(getattr(route, "name", "") != "frontend" for route in app.routes)


@pytest.mark.integration
async def test_frontend_static_mount_serves_index(tmp_path):
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<main>frontend</main>")
    app = FastAPI()
    mount_frontend(app, FrontendConfig(enabled=True), repo_root=tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ui/")

    assert response.status_code == 200
    assert "frontend" in response.text


@pytest.mark.integration
async def test_frontend_static_mount_falls_back_to_spa_index(tmp_path):
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<main>spa</main>")
    app = FastAPI()
    mount_frontend(app, FrontendConfig(enabled=True), repo_root=tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ui/projects/123")

    assert response.status_code == 200
    assert "spa" in response.text


@pytest.mark.unit
def test_frontend_static_mount_fails_when_enabled_assets_are_missing(tmp_path):
    app = FastAPI()

    with pytest.raises(RuntimeError, match="Frontend static assets are enabled"):
        mount_frontend(app, FrontendConfig(enabled=True), repo_root=tmp_path)


@pytest.mark.integration
async def test_api_routes_win_over_frontend_mount(tmp_path):
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<main>frontend</main>")
    app = FastAPI()

    @app.get("/ui/status")
    async def ui_status():
        return {"source": "api"}

    mount_frontend(app, FrontendConfig(enabled=True), repo_root=tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ui/status")

    assert response.status_code == 200
    assert response.json() == {"source": "api"}

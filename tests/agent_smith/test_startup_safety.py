from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from src.agent_smith import integration
from src.settings import Settings


class FakeServer:
    name = "memory - fake"

    def __init__(self) -> None:
        self.session_manager = self

    @asynccontextmanager
    async def run(self):
        yield


class FakeAdapter:
    started = False
    stopped = False

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    async def start(self) -> None:
        type(self).started = True

    async def stop(self) -> None:
        type(self).stopped = True


@pytest.mark.asyncio
async def test_agent_smith_routes_mount_without_feature_flag(agent_smith_client, monkeypatch):
    monkeypatch.delenv("AGENT_SMITH_ENABLED", raising=False)

    response = await agent_smith_client.get("/api/plans")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_production_startup_skips_seed_and_jobs_by_default(monkeypatch):
    app = SimpleNamespace(state=SimpleNamespace(settings=Settings(APP_ENV="production", _env_file=None)))
    monkeypatch.setattr(integration, "_mcp_servers", lambda: [FakeServer()])

    await integration.start_agent_smith_runtime(app)
    await integration.stop_agent_smith_runtime(app)

    assert not hasattr(app.state, "agent_smith_job_adapter")


@pytest.mark.asyncio
async def test_development_startup_preserves_seed_and_job_defaults(monkeypatch):
    from src.agent_smith import job_runtime
    from src.agent_smith.services import seed

    monkeypatch.delenv("AGENT_SMITH_AUTO_SEED", raising=False)
    monkeypatch.delenv("AGENT_SMITH_JOBS_ENABLED", raising=False)
    monkeypatch.delenv("AGENT_SMITH_LEGACY_SCHEDULER_ENABLED", raising=False)

    seed_called = False

    async def fake_seed_all() -> None:
        nonlocal seed_called
        seed_called = True

    FakeAdapter.started = False
    monkeypatch.setattr(seed, "seed_all", fake_seed_all)
    monkeypatch.setattr(job_runtime, "AgentSmithJobRuntimeAdapter", FakeAdapter)
    monkeypatch.setattr(integration, "_mcp_servers", lambda: [FakeServer()])
    app = SimpleNamespace(
        state=SimpleNamespace(settings=Settings(APP_ENV="development", _env_file=None), job_runtime=object())
    )

    await integration.start_agent_smith_runtime(app)
    await integration.stop_agent_smith_runtime(app)

    assert seed_called is True
    assert FakeAdapter.started is True


def test_deprecated_scheduler_flag_alias_still_works(monkeypatch, caplog):
    monkeypatch.delenv("AGENT_SMITH_JOBS_ENABLED", raising=False)
    monkeypatch.delenv("AGENT_SMITH_LEGACY_SCHEDULER_ENABLED", raising=False)
    settings = Settings(APP_ENV="production", AGENT_SMITH_JOBS_ENABLED=None, _env_file=None)
    monkeypatch.setenv("AGENT_SMITH_LEGACY_SCHEDULER_ENABLED", "true")

    enabled = integration._runtime_flag(
        settings,
        "AGENT_SMITH_JOBS_ENABLED",
        default=False,
        legacy_name="AGENT_SMITH_LEGACY_SCHEDULER_ENABLED",
    )

    assert enabled is True
    assert "AGENT_SMITH_LEGACY_SCHEDULER_ENABLED is deprecated" in caplog.text


def test_agent_smith_frontend_file_resolution_stays_under_dist(tmp_path):
    dist_dir = tmp_path / "frontend" / "dist"
    dist_dir.mkdir(parents=True)
    index_path = dist_dir / "index.html"
    index_path.write_text("<html></html>", encoding="utf-8")
    asset_path = dist_dir / "asset.txt"
    asset_path.write_text("asset", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")

    assert integration._safe_frontend_file(dist_dir, "asset.txt") == asset_path.resolve()
    assert integration._safe_frontend_file(dist_dir, "../secret.txt") == index_path.resolve()

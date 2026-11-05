import asyncio
from datetime import timedelta
import importlib
from threading import Event

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from services.costs import service
from services.api.routers.costs import router
from tests.test_costs import NOW
from tests.test_pinecone_costs_metrics import source
from services.costs.pinecone_metrics import parse_metrics


@pytest.fixture
def configured(monkeypatch, tmp_path):
    monkeypatch.setenv("PINECONE_COSTS_ENABLED", "true")
    monkeypatch.setenv("PINECONE_PROJECT_ID", "12345678-1234-1234-1234-123456789abc")
    monkeypatch.setenv("PINECONE_API_KEY", "PRIVATE_TEST_KEY")
    monkeypatch.setenv(
        "PINECONE_COSTS_RATES_JSON",
        '{"aws/us-east-1":{"read_usd_per_million":"2","write_usd_per_million":"4"}}',
    )
    monkeypatch.setenv("PINECONE_COSTS_PRICE_DATE", "2026-11-05")
    monkeypatch.setenv("COSTS_CACHE_PATH", str(tmp_path))


def test_disabled_and_missing_environment_never_request_metrics(monkeypatch):
    monkeypatch.delenv("PINECONE_COSTS_ENABLED", raising=False)
    assert service.read_pinecone_costs(NOW)["state"] == "disabled"
    monkeypatch.setenv("PINECONE_COSTS_ENABLED", "true")
    monkeypatch.delenv("PINECONE_PROJECT_ID", raising=False)
    result = service.read_pinecone_costs(NOW)
    assert result["state"] == "not_configured"
    assert "PINECONE_PROJECT_ID" in result["error"]["message"]


def test_http_polls_only_read_snapshot_and_collector_owns_external_calls(
    configured, monkeypatch
):
    metrics = importlib.import_module("services.costs.pinecone_metrics")
    calls = []

    def fetch(*args, **kwargs):
        calls.append(1)
        return parse_metrics(
            source("10" if len(calls) == 1 else "20", "5" if len(calls) == 1 else "15")
        )

    monkeypatch.setattr(metrics, "collect_metrics", fetch)
    app = FastAPI()
    app.include_router(router, prefix="/api/costs")
    with TestClient(app) as client:
        for _ in range(4):
            result = client.get("/api/costs/pinecone")
            assert result.status_code == 200
            assert result.json()["state"] == "pending"
        assert calls == []
        assert service.collect_pinecone_costs(NOW)["report"]["total"] is None
        assert len(calls) == 1
        service.collect_pinecone_costs(NOW + timedelta(seconds=15))
        assert len(calls) == 1
        observed = service.collect_pinecone_costs(NOW + timedelta(minutes=5))
        assert observed["report"]["total"] == "0.00006"
        for _ in range(4):
            payload = client.get("/api/costs/pinecone").json()
            assert payload["report"]["provider"] == "pinecone"
            assert "PRIVATE_TEST_KEY" not in str(payload)
            assert "counters" not in str(payload)
        assert len(calls) == 2


def test_invalid_prices_are_actionable_without_provider_calls(configured, monkeypatch):
    monkeypatch.setenv(
        "PINECONE_COSTS_RATES_JSON",
        '{"aws/us-east-1":{"read_usd_per_million":"NaN","write_usd_per_million":"4"}}',
    )
    result = service.read_pinecone_costs(NOW)
    assert result["state"] == "not_configured"
    assert "price" in result["error"]["message"].lower()
    assert result["report"] is None


@pytest.mark.asyncio
async def test_owned_collector_starts_once_and_waits_for_active_thread_on_shutdown(
    configured,
):
    module = importlib.import_module("services.costs.collector")
    entered, release = Event(), Event()
    calls = []

    def collect():
        calls.append(1)
        entered.set()
        assert release.wait(3)

    context = module.pinecone_collector(collect=collect)
    await context.__aenter__()
    assert await asyncio.to_thread(entered.wait, 2)
    stopping = asyncio.create_task(context.__aexit__(None, None, None))
    await asyncio.sleep(0)
    assert not stopping.done()
    release.set()
    await asyncio.wait_for(stopping, 2)
    assert calls == [1]


@pytest.mark.asyncio
async def test_disabled_collector_creates_no_worker(monkeypatch):
    module = importlib.import_module("services.costs.collector")
    monkeypatch.delenv("PINECONE_COSTS_ENABLED", raising=False)
    async with module.pinecone_collector(
        collect=lambda: pytest.fail("disabled collector ran")
    ):
        await asyncio.sleep(0)

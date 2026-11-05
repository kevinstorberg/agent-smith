from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from services.costs import service
from services.costs.contracts import CostReport
from services.api.routers.costs import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/costs")
    return TestClient(app)


def test_costs_disabled_requires_explicit_enable_and_no_provider_calls(
    client, monkeypatch
):
    monkeypatch.delenv("AWS_COSTS_ENABLED", raising=False)
    monkeypatch.setattr(
        service, "fetch_aws", lambda *a: pytest.fail("disabled cost provider called")
    )
    assert client.get("/api/costs/aws").json()["state"] == "disabled"


def test_costs_route_caches_repeated_polls_and_returns_safe_scope(
    client, monkeypatch, tmp_path
):
    monkeypatch.setenv("AWS_COSTS_ENABLED", "true")
    monkeypatch.setenv("COSTS_CACHE_PATH", str(tmp_path))
    calls = []

    def collect(now, profile):
        calls.append(1)
        return CostReport(
            provider="aws",
            period_start=now.date().replace(day=1),
            period_end=now.date(),
            currency="USD",
            total="1.23",
            estimated=True,
            scope="AWS account 123456789012",
            fetched_at=now,
        )

    monkeypatch.setattr(service, "fetch_aws", collect)
    for _ in range(4):
        data = client.get("/api/costs/aws").json()
        assert data["state"] == "ready"
        assert data["report"]["total"] == "1.23"
    assert calls == [1]


def test_costs_route_rejects_unknown_provider_and_invalid_configuration(
    client, monkeypatch
):
    assert client.get("/api/costs/private-provider").status_code == 404
    monkeypatch.setenv("AWS_COSTS_ENABLED", "maybe")
    data = client.get("/api/costs/aws").json()
    assert data["state"] == "not_configured"
    assert "true or false" in data["error"]["message"]


def test_costs_factory_blocks_real_billing_calls_in_automated_tests():
    from services.costs.aws import fetch_aws
    from services.costs.contracts import ProviderFailure

    with pytest.raises(ProviderFailure, match="automated_test"):
        fetch_aws(datetime.now(timezone.utc))

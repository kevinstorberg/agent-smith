from datetime import date, timedelta
from decimal import Decimal
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from services.api.routers import costs as costs_router
from services.costs import pinecone_metrics, service
from services.costs.pinecone_usage import PriceBook, build_usage
from tests.test_costs import NOW
from tests.test_pinecone_costs_metrics import source


PUBLISHED_RATES = [
    ("aws", "us-east-1", "16", "4"),
    ("aws", "us-west-2", "16", "4"),
    ("aws", "eu-west-1", "18", "4.50"),
    ("aws", "eu-central-1", "19", "5"),
    ("aws", "ap-southeast-1", "19", "5"),
    ("gcp", "us-central1", "16", "4"),
    ("gcp", "europe-west4", "18", "4.50"),
    ("azure", "eastus2", "16", "4"),
]
RATE_TEMPLATE = json.dumps(
    {
        "aws/us-east-1": {
            "read_usd_per_million": "REPLACE_WITH_READ_RATE",
            "write_usd_per_million": "REPLACE_WITH_WRITE_RATE",
        }
    }
)


def custom_rates(read="2", write="4"):
    return json.dumps(
        {
            "aws/us-east-1": {
                "read_usd_per_million": read,
                "write_usd_per_million": write,
            }
        }
    )


def test_no_price_environment_uses_a_dated_official_standard_reference():
    book = PriceBook.from_env({}, NOW)
    assert book is not None
    assert book.as_of == date(2026, 11, 5)
    assert book.source == "https://www.pinecone.io/pricing/"
    assert set(book.rates) == {
        f"{cloud}/{region}" for cloud, region, *_ in PUBLISHED_RATES
    }


@pytest.mark.parametrize("cloud,region,read,write", PUBLISHED_RATES)
def test_each_official_region_prices_observed_units_at_its_published_rates(
    cloud, region, read, write
):
    book = PriceBook.from_env({}, NOW)
    assert book is not None
    first = build_usage(
        NOW,
        pinecone_metrics.parse_metrics(source(cloud=cloud, region=region)),
        None,
        book,
        Decimal("50"),
    )
    second = build_usage(
        NOW + timedelta(minutes=5),
        pinecone_metrics.parse_metrics(source("20", "15", cloud=cloud, region=region)),
        first.state,
        book,
        Decimal("50"),
    )
    assert Decimal(second.report.total) == (Decimal(read) + Decimal(write)) / 100_000


def test_complete_unfilled_price_template_uses_defaults_without_manual_date():
    book = PriceBook.from_env(
        {
            "PINECONE_COSTS_RATES_JSON": RATE_TEMPLATE,
            "PINECONE_COSTS_PRICE_DATE": "REPLACE_WITH_VERIFICATION_DATE",
            "PINECONE_COSTS_PRICE_SOURCE": "REPLACE_WITH_PRICE_SOURCE",
        },
        NOW,
    )
    assert book == PriceBook.from_env({}, NOW)


def test_real_subset_override_has_deterministic_reference_date_without_date_entry():
    env = {"PINECONE_COSTS_RATES_JSON": custom_rates()}
    first = PriceBook.from_env(env, NOW)
    later = PriceBook.from_env(env, NOW + timedelta(days=40))
    assert first == later
    assert first.as_of == date(2026, 11, 5)
    assert set(first.rates) == {"aws/us-east-1"}
    assert first.rates["aws/us-east-1"].read_usd_per_million == Decimal("2")


@pytest.mark.parametrize(
    "raw",
    [
        "not JSON",
        "null",
        "[]",
        "{}",
        custom_rates("2", "REPLACE_WITH_WRITE_RATE"),
        custom_rates("", ""),
        custom_rates("-1", "4"),
        custom_rates("NaN", "4"),
        custom_rates("Infinity", "4"),
        '{"aws/us-east-1":{"read_usd_per_million":"REPLACE_WITH_READ_RATE",'
        '"write_usd_per_million":"REPLACE_WITH_WRITE_RATE","extra":"REPLACE_WITH_EXTRA"}}',
        '{"not-a-scope":{"read_usd_per_million":"REPLACE_WITH_READ_RATE",'
        '"write_usd_per_million":"REPLACE_WITH_WRITE_RATE"}}',
    ],
)
def test_real_malformed_or_partially_filled_overrides_are_not_silently_discarded(raw):
    with pytest.raises(ValueError):
        PriceBook.from_env({"PINECONE_COSTS_RATES_JSON": raw}, NOW)


@pytest.mark.parametrize(
    "name,value",
    [
        ("PINECONE_COSTS_PRICE_DATE", "invalid-date"),
        ("PINECONE_COSTS_PRICE_DATE", "2027-01-01"),
        ("PINECONE_COSTS_PRICE_SOURCE", "javascript:PRIVATE_OVERRIDE"),
        (
            "PINECONE_COSTS_PRICE_SOURCE",
            "https://PRIVATE_USER:PRIVATE_KEY@example.test/",
        ),
    ],
)
def test_bad_real_metadata_overrides_fail_without_echoing_values(name, value):
    with pytest.raises(ValueError) as raised:
        PriceBook.from_env(
            {"PINECONE_COSTS_RATES_JSON": custom_rates(), name: value}, NOW
        )
    assert "PRIVATE" not in str(raised.value)


def test_default_prices_do_not_reprice_older_custom_intervals_or_change_their_hash():
    legacy = PriceBook.from_env(
        {
            "PINECONE_COSTS_RATES_JSON": custom_rates(),
            "PINECONE_COSTS_PRICE_DATE": "2026-11-05",
        },
        NOW,
    )
    first = build_usage(
        NOW, pinecone_metrics.parse_metrics(source()), None, legacy, Decimal("50")
    )
    second = build_usage(
        NOW + timedelta(minutes=5),
        pinecone_metrics.parse_metrics(source("20", "15")),
        first.state,
        legacy,
        Decimal("50"),
    )
    old_books = json.loads(json.dumps(second.state["prices"]))
    updated = build_usage(
        NOW + timedelta(minutes=10),
        pinecone_metrics.parse_metrics(source("30", "25")),
        second.state,
        PriceBook.from_env({}, NOW),
        Decimal("50"),
    )
    assert updated.report.total == "0.00026"
    assert len(updated.state["prices"]) == 2
    assert {key: updated.state["prices"][key] for key in old_books} == old_books


def test_unpublished_region_keeps_quantities_and_names_the_missing_price():
    book = PriceBook.from_env({}, NOW)
    first = build_usage(
        NOW,
        pinecone_metrics.parse_metrics(source(region="future-region")),
        None,
        book,
        Decimal("50"),
    )
    second = build_usage(
        NOW + timedelta(minutes=5),
        pinecone_metrics.parse_metrics(source("20", "15", region="future-region")),
        first.state,
        book,
        Decimal("50"),
    )
    assert second.report.total is None
    assert second.report.usage[0]["amount"] == "10"
    assert any("aws/future-region" in note for note in second.report.notes)


@pytest.fixture
def configured(monkeypatch, tmp_path):
    monkeypatch.setenv("PINECONE_COSTS_ENABLED", "true")
    monkeypatch.setenv("PINECONE_PROJECT_ID", "12345678-1234-1234-1234-123456789abc")
    monkeypatch.setenv("PINECONE_API_KEY", "SYNTHETIC_KEY")
    monkeypatch.setenv("COSTS_CACHE_PATH", str(tmp_path))
    for name in ("RATES_JSON", "PRICE_DATE", "PRICE_SOURCE", "MONTHLY_MINIMUM_USD"):
        monkeypatch.delenv("PINECONE_COSTS_" + name, raising=False)


def test_existing_key_and_project_reach_default_estimate_without_price_configuration(
    configured,
    monkeypatch,
):
    monkeypatch.setenv("PINECONE_COSTS_RATES_JSON", RATE_TEMPLATE)
    monkeypatch.setenv("PINECONE_COSTS_PRICE_DATE", "YYYY-MM-DD")
    monkeypatch.setenv("PINECONE_COSTS_MONTHLY_MINIMUM_USD", "REPLACE_WITH_MINIMUM")
    requests, samples = [], []

    def respond(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer SYNTHETIC_KEY"
        if request.url.host == "api.pinecone.io":
            return httpx.Response(
                200, json=[{"targets": ["metrics.pinecone.io"], "labels": {}}]
            )
        samples.append(1)
        return httpx.Response(
            200, text=source("10", "5") if len(samples) == 1 else source("20", "15")
        )

    actual_collect = pinecone_metrics.collect_metrics
    actual_read = service.read_pinecone_costs
    monkeypatch.setattr(
        costs_router,
        "read_pinecone_costs",
        lambda: actual_read(NOW + timedelta(minutes=6)),
    )
    app = FastAPI()
    app.include_router(costs_router.router, prefix="/api/costs")
    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as transport,
        TestClient(app) as client,
    ):
        monkeypatch.setattr(
            pinecone_metrics,
            "collect_metrics",
            lambda project, key: actual_collect(project, key, client=transport),
        )
        assert client.get("/api/costs/pinecone").json()["state"] == "pending"
        first = service.collect_pinecone_costs(NOW)
        assert first["report"]["total"] is None
        second = service.collect_pinecone_costs(NOW + timedelta(minutes=5))
        assert second["report"]["total"] == "0.0002"
        assert any("USD 50" in note for note in second["report"]["notes"])
        for _ in range(4):
            assert (
                client.get("/api/costs/pinecone").json()["report"]["total"] == "0.0002"
            )
        assert len(requests) == 4


@pytest.mark.parametrize(
    "project", ["REPLACE_WITH_PINECONE_PROJECT_ID", "YOUR_PROJECT_ID"]
)
def test_project_placeholder_fails_before_metrics_instead_of_inventing_discovery(
    configured,
    monkeypatch,
    project,
):
    monkeypatch.setenv("PINECONE_PROJECT_ID", project)
    monkeypatch.setattr(
        pinecone_metrics,
        "collect_metrics",
        lambda *_: pytest.fail("placeholder project reached provider"),
    )
    result = service.collect_pinecone_costs(NOW)
    assert result["state"] == "not_configured"
    assert "PINECONE_PROJECT_ID" in result["error"]["message"]
    assert project not in json.dumps(result) and "SYNTHETIC_KEY" not in json.dumps(
        result
    )


def test_custom_rates_have_explicit_unverified_provenance_without_requiring_a_date(
    configured,
    monkeypatch,
):
    monkeypatch.setenv("PINECONE_COSTS_RATES_JSON", custom_rates())
    monkeypatch.setattr(
        pinecone_metrics,
        "collect_metrics",
        lambda *_: pinecone_metrics.parse_metrics(source()),
    )
    result = service.collect_pinecone_costs(NOW)
    assert result["state"] == "ready"
    assert any(
        "override" in note.lower() and "not" in note.lower() and "verif" in note.lower()
        for note in result["report"]["notes"]
    )

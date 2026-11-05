from datetime import datetime, timedelta
from decimal import Decimal
import importlib

import pytest

from services.costs.contracts import ProviderFailure
from services.costs.pinecone_metrics import parse_metrics
from tests.test_pinecone_costs_metrics import source
from tests.test_costs import NOW


def module():
    return importlib.import_module("services.costs.pinecone_usage")


def prices():
    return module().PriceBook.model_validate(
        {
            "as_of": "2026-11-05",
            "source": "https://www.pinecone.io/pricing/",
            "rates": {
                "aws/us-east-1": {
                    "read_usd_per_million": "2",
                    "write_usd_per_million": "4",
                }
            },
        }
    )


def collect(at=NOW, previous=None, read="10", write="5", book=True, **sample_options):
    return module().build_usage(
        at,
        parse_metrics(source(read, write, **sample_options)),
        previous,
        prices() if book else None,
        Decimal("50"),
    )


def test_first_sample_is_baseline_unavailable_not_zero_and_storage_quantity_only():
    first = collect()
    assert first.report.total is None
    assert first.report.coverage_start == NOW
    assert first.report.daily == []
    assert any(
        row["amount"] == "4096" and row["unit"] == "bytes" for row in first.report.usage
    )
    assert any(
        "unavailable" in note.lower() and "baseline" in note.lower()
        for note in first.report.notes
    )
    assert any(
        "storage" in note.lower() and "excluded" in note.lower()
        for note in first.report.notes
    )


def test_persisted_counter_deltas_are_priced_exactly_without_adding_minimum():
    first = collect()
    second = collect(NOW + timedelta(minutes=5), first.state, read="20", write="15")
    assert Decimal(second.report.total) == Decimal("0.00006")
    assert second.report.daily == [{"label": "2026-11-05", "amount": "0.00006"}]
    assert any("50" in note and "commitment" in note for note in second.report.notes)
    assert second.report.period_start.isoformat() == "2026-11-01"
    assert second.report.cost_basis != "UnblendedCost"


def test_repeated_samples_and_process_restart_do_not_reprice_old_counters():
    first = collect()
    second = collect(NOW + timedelta(minutes=5), first.state, read="20", write="15")
    third = collect(NOW + timedelta(minutes=10), second.state, read="20", write="15")
    assert Decimal(third.report.total) == Decimal(second.report.total)
    assert third.report.coverage_start == NOW


@pytest.mark.parametrize("later", [timedelta(minutes=16), timedelta(days=1)])
def test_long_gaps_are_excluded_instead_of_filling_missing_usage(later):
    result = collect(NOW + later, collect().state, read="100000", write="100000")
    assert result.report.total is None
    assert any(
        "gap" in note.lower() or "boundary" in note.lower()
        for note in result.report.notes
    )


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-11-05T23:58:00+00:00", "2026-11-06T00:03:00+00:00"),
        ("2026-11-30T23:58:00+00:00", "2026-12-01T00:03:00+00:00"),
    ],
)
def test_day_and_month_boundaries_are_never_silently_prorated(start, end):
    first = collect(datetime.fromisoformat(start))
    result = collect(
        datetime.fromisoformat(end), first.state, read="1000", write="2000"
    )
    assert result.report.total is None
    assert result.report.daily == []
    assert any("boundary" in note.lower() for note in result.report.notes)
    interval = result.state["intervals"][-1]
    assert datetime.fromisoformat(interval["start"]) == datetime.fromisoformat(start)
    assert datetime.fromisoformat(interval["end"]) == datetime.fromisoformat(end)


def test_counter_reset_and_new_series_skip_the_unknown_portion():
    first = collect()
    reset = collect(NOW + timedelta(minutes=5), first.state, read="1", write="1")
    assert reset.report.total is None
    assert any("reset" in note.lower() for note in reset.report.notes)
    newer = collect(
        NOW + timedelta(minutes=10),
        reset.state,
        read="100",
        write="100",
        instance="new",
    )
    assert newer.report.total is None
    assert any("series" in note.lower() for note in newer.report.notes)


def test_missing_rates_keep_usage_visible_without_guessing_a_dollar_estimate():
    first = collect(book=False)
    result = collect(
        NOW + timedelta(minutes=5), first.state, read="20", write="15", book=False
    )
    assert result.report.total is None
    assert any(row["amount"] == "10" for row in result.report.usage)
    assert any("price" in note.lower() for note in result.report.notes)


def test_prices_are_stamped_and_changed_rates_do_not_reprice_previous_intervals():
    first = collect()
    second = collect(NOW + timedelta(minutes=5), first.state, read="20", write="15")
    updated = prices().model_copy(
        update={
            "as_of": NOW.date(),
            "rates": {
                "aws/us-east-1": module().UsageRate(
                    read_usd_per_million="4", write_usd_per_million="8"
                )
            },
        }
    )
    result = module().build_usage(
        NOW + timedelta(minutes=10),
        parse_metrics(source("30", "25")),
        second.state,
        updated,
        Decimal("50"),
    )
    assert Decimal(result.report.total) == Decimal("0.00018")
    assert len(result.state["prices"]) == 2


def test_stale_price_date_is_visible_and_unsupported_capacity_is_never_priced():
    stale = prices().model_copy(update={"as_of": NOW.date() - timedelta(days=31)})
    result = module().build_usage(
        NOW, parse_metrics(source()), None, stale, Decimal("50")
    )
    assert any("30 days" in note for note in result.report.notes)
    first = collect(mode="byoc")
    result = collect(
        NOW + timedelta(minutes=5), first.state, read="20", write="15", mode="byoc"
    )
    assert result.report.total is None
    assert any("capacity" in note.lower() for note in result.report.notes)


def test_default_reference_and_overrides_reject_negative_nonfinite_or_future_values():
    assert module().PriceBook.from_env({}, NOW).as_of == NOW.date()
    for value in ("-1", "NaN", "Infinity"):
        with pytest.raises(ValueError):
            module().PriceBook.from_env(
                {
                    "PINECONE_COSTS_PRICE_DATE": "2026-11-05",
                    "PINECONE_COSTS_RATES_JSON": '{"aws/us-east-1":{"read_usd_per_million":"'
                    + value
                    + '","write_usd_per_million":"4"}}',
                },
                NOW,
            )
    with pytest.raises(ValueError):
        module().PriceBook.from_env(
            {
                "PINECONE_COSTS_PRICE_DATE": "2027-01-01",
                "PINECONE_COSTS_RATES_JSON": '{"aws/us-east-1":{"read_usd_per_million":"2","write_usd_per_million":"4"}}',
            },
            NOW,
        )


def test_contiguous_same_day_ranges_compact_without_losing_cost_or_boundary_bounds():
    current = collect()
    for index in range(1, 101):
        current = collect(
            NOW + timedelta(minutes=5 * index),
            current.state,
            read=str(10 + index),
            write=str(5 + index),
        )
    assert len(current.state["intervals"]) == 1
    assert Decimal(current.report.total) == Decimal("0.0006")
    assert datetime.fromisoformat(current.state["intervals"][0]["start"]) == NOW
    assert datetime.fromisoformat(
        current.state["intervals"][0]["end"]
    ) == NOW + timedelta(minutes=500)


def test_corrupt_pricing_stamp_is_rejected_without_hidden_repricing():
    first = collect()
    second = collect(NOW + timedelta(minutes=5), first.state, read="20", write="15")
    stamp = next(iter(second.state["prices"]))
    second.state["prices"][stamp]["rates"]["aws/us-east-1"]["read_usd_per_million"] = (
        "9999"
    )
    with pytest.raises(ProviderFailure, match="invalid_snapshot"):
        collect(NOW + timedelta(minutes=10), second.state, read="30", write="25")


@pytest.mark.parametrize(
    "link",
    ["javascript:alert(1)", "https://user:PRIVATE_PASSWORD@example.invalid/pricing"],
)
def test_report_pricing_links_reject_scripts_and_embedded_credentials(link):
    from pydantic import ValidationError
    from services.costs.contracts import CostReport

    payload = collect().report.model_dump(mode="json")
    payload["pricing_source"] = link
    with pytest.raises(ValidationError):
        CostReport.model_validate(payload)


def test_browser_fixture_is_exact_native_backend_output():
    import json
    from pathlib import Path

    fixture = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "services/client/src/pages/__tests__/pineconeCostsFixture.json"
        ).read_text()
    )
    first = collect()
    second = collect(NOW + timedelta(minutes=5), first.state, read="20", write="15")
    unpriced = collect(
        NOW + timedelta(minutes=5), first.state, read="20", write="15", book=False
    )
    assert fixture["baseline"] == first.report.model_dump(mode="json")
    assert fixture["observed"] == second.report.model_dump(mode="json")
    assert fixture["no_price"] == unpriced.report.model_dump(mode="json")
    boundary = datetime.fromisoformat("2026-11-01T00:15:00+00:00")
    book = prices().model_copy(update={"as_of": boundary.date()})
    assert fixture["utc_boundary"] == module().build_usage(
        boundary, parse_metrics(source()), None, book, Decimal("50")
    ).report.model_dump(mode="json")

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from services.costs.aws import collect_aws, month_window
from services.costs.cache import SnapshotCache
from services.costs.contracts import CostReport, ProviderFailure


NOW = datetime(2026, 11, 5, 15, 0, tzinfo=timezone.utc)


def report(now=NOW):
    return CostReport(
        provider="aws",
        period_start="2026-11-01",
        period_end="2026-11-06",
        currency="USD",
        total="12.25",
        estimated=True,
        scope="AWS billing visible to account 123456789012",
        fetched_at=now,
    )


def test_costs_window_is_current_utc_month_even_for_local_timezone():
    start, end = month_window(datetime.fromisoformat("2026-10-31T23:30:00-05:00"))
    assert (start, end) == ("2026-11-01", "2026-11-02")


def test_costs_aws_provider_labels_explain_chargeable_and_free_requests():
    from scripts.shared.operation_logging import provider_label

    assert (
        provider_label("aws_cost_explorer", "get_cost_and_usage").prefix
        == "AWS COST EXPLORER READ [BILLABLE]"
    )
    assert (
        provider_label("aws_sts", "get_caller_identity").prefix
        == "AWS IDENTITY READ [NONBILLABLE]"
    )
    assert provider_label("aws_sts", "unknown_operation").billing == "unknown"


def test_costs_cache_survives_restart_and_ui_polls_do_not_fetch(tmp_path):
    calls = []

    def fetch():
        calls.append(1)
        return report()

    first = SnapshotCache(tmp_path, "aws", "profile:personal")
    assert first.read_or_refresh(NOW, fetch)["state"] == "ready"
    for minute in (1, 2, 10, 60, 1439):
        cached = SnapshotCache(tmp_path, "aws", "profile:personal")
        assert (
            cached.read_or_refresh(NOW + timedelta(minutes=minute), fetch)["report"][
                "total"
            ]
            == "12.25"
        )
    assert len(calls) == 1
    assert list(tmp_path.glob("*.json"))[0].stat().st_mode & 0o777 == 0o600


def test_costs_failed_refresh_retains_success_and_has_bounded_retries(tmp_path):
    cache = SnapshotCache(tmp_path, "aws", "scope")
    cache.read_or_refresh(NOW, report)

    def failure():
        raise ProviderFailure(
            "permission_denied", "Grant read-only Cost Explorer access."
        )

    later = NOW + timedelta(days=1)
    result = cache.read_or_refresh(later, failure)
    assert result["state"] == "stale"
    assert result["report"]["total"] == "12.25"
    assert result["error"]["code"] == "permission_denied"
    calls = []

    def fail_counted():
        calls.append(1)
        raise ProviderFailure("unavailable", "Provider temporarily unavailable.")

    for minute in (1, 15, 30, 60, 90, 120, 150):
        cache.read_or_refresh(later + timedelta(minutes=minute), fail_counted)
    assert len(calls) == 2


def test_costs_crash_marks_attempt_before_fetch_and_scopes_are_isolated(tmp_path):
    cache = SnapshotCache(tmp_path, "aws", "one")

    def crash():
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        cache.read_or_refresh(NOW, crash)
    calls = []
    result = SnapshotCache(tmp_path, "aws", "one").read_or_refresh(
        NOW + timedelta(seconds=15), lambda: calls.append(1)
    )
    assert not calls
    assert result["state"] == "failed"
    assert (
        SnapshotCache(tmp_path, "aws", "two").read_or_refresh(NOW, report)["state"]
        == "ready"
    )


def test_costs_refuses_corrupt_or_symlink_snapshots(tmp_path):
    cache = SnapshotCache(tmp_path, "aws", "scope")
    cache.read_or_refresh(NOW, report)
    snapshot = next(tmp_path.glob("*.json"))
    snapshot.write_text('{"schema_version": 99}')
    with pytest.raises(ValueError, match="snapshot"):
        cache.read_or_refresh(NOW, report)
    snapshot.unlink()
    target = tmp_path / "target"
    target.write_text("private")
    snapshot.symlink_to(target)
    with pytest.raises(ValueError, match="symbolic"):
        cache.read_or_refresh(NOW, report)
    assert target.read_text() == "private"


def test_costs_contended_refresh_returns_pending_without_second_fetch(tmp_path):
    from scripts.shared.atomic_json import exclusive_file_lock

    cache = SnapshotCache(tmp_path, "aws", "scope")
    calls = []
    with exclusive_file_lock(cache.lock_path):
        result = cache.read_or_refresh(NOW, lambda: calls.append(1))
    assert result["state"] == "pending"
    assert not calls


def test_costs_active_refresh_is_pending_for_both_read_paths(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    cache = SnapshotCache(tmp_path, "aws", "scope")
    entered, release = Event(), Event()

    def fetch():
        entered.set()
        assert release.wait(5)
        return report()

    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(cache.read_or_refresh, NOW, fetch)
        assert entered.wait(5)
        try:
            assert cache.read()["state"] == "pending"
            assert (
                SnapshotCache(tmp_path, "aws", "scope").read_or_refresh(
                    NOW + timedelta(seconds=15),
                    lambda: pytest.fail("second provider call"),
                )["state"]
                == "pending"
            )
        finally:
            release.set()
        assert future.result(5)["state"] == "ready"
    assert cache.read()["state"] == "ready"


def test_costs_exhausted_daily_budget_reports_next_utc_day(tmp_path):
    cache = SnapshotCache(tmp_path, "aws", "scope")

    def failure():
        raise ProviderFailure("unavailable", "Provider temporarily unavailable.")

    for minutes in (0, 30, 60, 90):
        result = cache.read_or_refresh(NOW + timedelta(minutes=minutes), failure)
    assert result["state"] == "failed"
    assert datetime.fromisoformat(result["next_refresh_at"]) == datetime(
        2026, 11, 6, tzinfo=timezone.utc
    )


class Client:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []

    def get_cost_and_usage(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.pages)


def page(amount, *, service="Amazon Bedrock", token=None, currency="USD"):
    result = {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2026-11-04", "End": "2026-11-05"},
                "Estimated": True,
                "Groups": [
                    {
                        "Keys": [service],
                        "Metrics": {
                            "UnblendedCost": {"Amount": amount, "Unit": currency}
                        },
                    }
                ],
            }
        ]
    }
    if token:
        result["NextPageToken"] = token
    return result


def test_costs_aws_paginates_and_preserves_refunds_with_real_decimal_math():
    client = Client([page("0.1", token="next"), page("-0.03", service="AWS Credits")])
    data = collect_aws(client, "123456789012", NOW)
    assert Decimal(data.total) == Decimal("0.07")
    assert data.estimated is True
    assert len(data.breakdown) == 2
    assert data.daily == [{"label": "2026-11-04", "amount": "0.07"}]
    assert client.calls[1]["NextPageToken"] == "next"
    assert client.calls[0]["Metrics"] == ["UnblendedCost"]


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "not-a-cost"])
def test_costs_aws_rejects_invalid_amounts_without_replacing_data(bad):
    with pytest.raises(ProviderFailure, match="invalid_response"):
        collect_aws(Client([page(bad)]), "123456789012", NOW)


def test_costs_aws_rejects_mixed_currencies_and_repeated_page_tokens():
    with pytest.raises(ProviderFailure, match="invalid_response"):
        collect_aws(
            Client([page("1", token="more"), page("2", currency="EUR")]),
            "123456789012",
            NOW,
        )
    with pytest.raises(ProviderFailure, match="invalid_response"):
        collect_aws(
            Client([page("1", token="more"), page("2", token="more")]),
            "123456789012",
            NOW,
        )


def test_costs_aws_allows_ungrouped_credits_and_empty_service_labels():
    data = page("-2", service="")
    assert collect_aws(Client([data]), "123456789012", NOW).breakdown == [
        {"label": "Unspecified service", "amount": "-2"}
    ]
    data["ResultsByTime"][0]["Groups"] = []
    data["ResultsByTime"][0]["Total"] = {
        "UnblendedCost": {"Amount": "-3", "Unit": "USD"}
    }
    assert collect_aws(Client([data]), "123456789012", NOW).total == "-3"


def test_costs_native_sdk_clients_are_closed_after_refresh(monkeypatch):
    boto3 = pytest.importorskip("boto3")
    from botocore.credentials import Credentials
    from botocore.stub import Stubber
    from types import SimpleNamespace
    from services.costs.aws import fetch_aws

    session = boto3.Session(
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
        aws_session_token="testing",
    )
    sts = session.client("sts", region_name="us-east-1")
    ce = session.client("ce", region_name="us-east-1")
    clients = {"sts": sts, "ce": ce}
    closed = []
    for name, client in clients.items():
        original = client.close
        monkeypatch.setattr(
            client,
            "close",
            lambda name=name, original=original: (closed.append(name), original())[1],
        )
    fake_session = SimpleNamespace(
        get_credentials=lambda: Credentials("testing", "testing", "testing"),
        client=lambda service, **kwargs: clients[service],
    )
    monkeypatch.setattr(boto3, "Session", lambda **kwargs: fake_session)
    monkeypatch.setattr(
        "scripts.shared.automated_tests.automated_tests_enabled", lambda: False
    )
    with Stubber(sts) as identity_stub, Stubber(ce) as cost_stub:
        identity_stub.add_response(
            "get_caller_identity",
            {
                "UserId": "offline-user",
                "Account": "123456789012",
                "Arn": "arn:aws:iam::123456789012:user/offline",
            },
        )
        cost_stub.add_response(
            "get_cost_and_usage",
            page("1.25"),
            {
                "TimePeriod": {"Start": "2026-11-01", "End": "2026-11-06"},
                "Granularity": "DAILY",
                "Metrics": ["UnblendedCost"],
                "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
            },
        )
        assert fetch_aws(NOW).total == "1.25"
        identity_stub.assert_no_pending_responses()
        cost_stub.assert_no_pending_responses()
    assert closed == ["sts", "ce"]

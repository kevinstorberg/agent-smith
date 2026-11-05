from decimal import Decimal
import importlib
from types import SimpleNamespace

import httpx
import pytest

from services.costs.contracts import ProviderFailure


def source(
    read="10",
    write="5",
    *,
    mode="serverless",
    instance="one",
    cloud="aws",
    region="us-east-1",
):
    common = f'index_name="synthetic",cloud="{cloud}",region="{region}",capacity_mode="{mode}"'
    return f'''# TYPE pinecone_db_read_unit_count counter
pinecone_db_read_unit_count{{{common},instance="{instance}"}} {read}
# TYPE pinecone_db_write_unit_count counter
pinecone_db_write_unit_count{{{common},instance="{instance}"}} {write}
# TYPE pinecone_db_storage_size_bytes gauge
pinecone_db_storage_size_bytes{{{common}}} 4096
'''


def module():
    return importlib.import_module("services.costs.pinecone_metrics")


def test_native_parser_uses_documented_counter_types_and_normalized_samples():
    sample = module().parse_metrics(source(read="10.25"))
    assert sorted(point.metric for point in sample.counters.values()) == [
        "read_units",
        "write_units",
    ]
    assert {point.value for point in sample.counters.values()} == {
        Decimal("10.25"),
        Decimal("5"),
    }
    assert next(iter(sample.storage.values())).value == Decimal("4096")
    assert all(len(key) == 64 for key in sample.counters)


@pytest.mark.parametrize("bad", ["NaN", "+Inf", "-1"])
def test_nonfinite_or_negative_counters_are_rejected(bad):
    with pytest.raises(ProviderFailure):
        module().parse_metrics(source(read=bad))


@pytest.mark.parametrize(
    "text",
    [
        source().replace("read_unit_count counter", "read_unit_count gauge"),
        source().replace(',instance="one"', ""),
        "# TYPE unrelated counter\nunrelated 1\n",
    ],
)
def test_unknown_types_missing_identity_or_absent_usage_never_imply_zero(text):
    with pytest.raises(ProviderFailure):
        module().parse_metrics(text)


def test_discovery_and_native_http_scrape_are_read_only_bounded_and_authenticated():
    requests = []

    def respond(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer PRIVATE_TEST_KEY"
        if request.url.host == "api.pinecone.io":
            return httpx.Response(
                200,
                json=[
                    {
                        "targets": ["metrics.us-east-1.pinecone.io:443"],
                        "labels": {
                            "__scheme__": "https",
                            "__metrics_path__": "/metrics",
                        },
                    }
                ],
            )
        assert request.url.host == "metrics.us-east-1.pinecone.io"
        return httpx.Response(200, text=source())

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        sample = module().collect_metrics(
            "12345678-1234-1234-1234-123456789abc", "PRIVATE_TEST_KEY", client=client
        )
    assert len(requests) == 2
    assert len(sample.counters) == 2


@pytest.mark.parametrize(
    "target,labels",
    [
        ("127.0.0.1:443", {}),
        ("pinecone.io.evil.invalid:443", {}),
        ("metrics.pinecone.io:80", {}),
        ("user@metrics.pinecone.io:443", {}),
        ("metrics.pinecone.io", {"__scheme__": "http"}),
        ("metrics.pinecone.io", {"__metrics_path__": "/../private"}),
    ],
)
def test_discovery_cannot_send_project_credentials_to_unsafe_targets(target, labels):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=[{"targets": [target], "labels": labels}])

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ProviderFailure):
            module().collect_metrics(
                "12345678-1234-1234-1234-123456789abc",
                "PRIVATE_TEST_KEY",
                client=client,
            )
    assert len(requests) == 1


def test_redirects_are_never_followed_with_credentials():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            302, headers={"Location": "https://never-contact.invalid/steal"}
        )

    with httpx.Client(
        transport=httpx.MockTransport(respond), follow_redirects=True
    ) as client:
        with pytest.raises(ProviderFailure):
            module().collect_metrics(
                "12345678-1234-1234-1234-123456789abc",
                "PRIVATE_TEST_KEY",
                client=client,
            )
    assert len(requests) == 1


def test_metric_point_limit_applies_to_the_complete_collection(monkeypatch):
    metrics = module()
    monkeypatch.setattr(metrics, "MAX_POINTS", 4, raising=False)

    def respond(request):
        if request.url.host == "api.pinecone.io":
            return httpx.Response(
                200,
                json=[
                    {
                        "targets": ["one.pinecone.io", "two.pinecone.io"],
                        "labels": {},
                    }
                ],
            )
        return httpx.Response(200, text=source(instance=request.url.host))

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ProviderFailure) as raised:
            metrics.collect_metrics("project-test", "PRIVATE_TEST_KEY", client=client)
    assert raised.value.code == "metrics_limit"


@pytest.mark.parametrize("limit", ["MAX_RESPONSE", "MAX_TOTAL"])
def test_body_limits_fail_without_exposing_credentials(monkeypatch, limit):
    metrics = module()
    monkeypatch.setattr(metrics, limit, 100)
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.host == "api.pinecone.io":
            return httpx.Response(
                200, json=[{"targets": ["one.pinecone.io"], "labels": {}}]
            )
        return httpx.Response(200, text=source())

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ProviderFailure) as raised:
            metrics.collect_metrics("project-test", "PRIVATE_TEST_KEY", client=client)
    assert raised.value.code == "metrics_limit"
    assert len(requests) == 2
    assert "PRIVATE" not in str(raised.value) + raised.value.message


def test_expired_collection_does_not_start_another_http_request(monkeypatch):
    metrics = module()
    ticks = iter([0, 0, 31])
    monkeypatch.setattr(metrics, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200, json=[{"targets": ["one.pinecone.io"], "labels": {}}]
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ProviderFailure) as raised:
            metrics.collect_metrics("project-test", "PRIVATE_TEST_KEY", client=client)
    assert raised.value.code == "metrics_limit"
    assert len(requests) == 1

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import ipaddress
import json
import re
import time
from urllib.parse import urlsplit

import httpx

from services.costs.contracts import ProviderFailure
from services.observability import billable_operation


_COUNTERS = {
    "pinecone_db_read_unit_count": "read_units",
    "pinecone_db_write_unit_count": "write_units",
}
_STORAGE = "pinecone_db_storage_size_bytes"
_DRN = {
    "pinecone_db_drn_cpu_usage_percent",
    "pinecone_db_index_fullness",
    "pinecone_db_index_memory_fullness",
    "pinecone_db_index_storage_fullness",
}
_BASE_LABELS = {"index_name", "cloud", "region", "capacity_mode"}
MAX_RESPONSE = 2_000_000
MAX_TOTAL = 8_000_000
MAX_TARGETS = 32
MAX_POINTS = 4000
DEADLINE_SECONDS = 30


def failure(
    code="invalid_metrics",
    message="Pinecone returned unsupported metrics; check the documented monitoring integration.",
):
    return ProviderFailure(code, message)


@dataclass(frozen=True)
class MetricPoint:
    metric: str
    labels: dict[str, str]
    value: Decimal

    @property
    def group(self) -> str:
        return json.dumps(
            [
                self.labels[key]
                for key in ("index_name", "cloud", "region", "capacity_mode")
            ],
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class MetricSample:
    counters: dict[str, MetricPoint] = field(default_factory=dict)
    storage: dict[str, MetricPoint] = field(default_factory=dict)
    unsupported: frozenset[str] = frozenset()


def _labels(labels, *, counter=False):
    required = _BASE_LABELS | ({"instance"} if counter else set())
    if set(labels) != required or any(
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or any(ord(c) < 32 for c in value)
        for value in labels.values()
    ):
        raise failure()
    return dict(labels)


def parse_metrics(text: str) -> MetricSample:
    from prometheus_client.parser import text_string_to_metric_families

    counters, storage, unsupported = {}, {}, set()
    try:
        for family in text_string_to_metric_families(text):
            if family.name in _DRN:
                for sample in family.samples:
                    if _BASE_LABELS <= sample.labels.keys():
                        labels = _labels(
                            {key: sample.labels[key] for key in _BASE_LABELS}
                        )
                        unsupported.add(MetricPoint("", labels, Decimal(0)).group)
                continue
            if family.name not in {*_COUNTERS, _STORAGE}:
                continue
            counter = family.name in _COUNTERS
            if family.type != ("counter" if counter else "gauge"):
                raise failure()
            for sample in family.samples:
                # The official parser normalizes counter samples with a _total suffix.
                if sample.name != family.name + ("_total" if counter else ""):
                    continue
                labels = _labels(sample.labels, counter=counter)
                value = Decimal(str(sample.value))
                if not value.is_finite() or value < 0:
                    raise failure()
                metric = _COUNTERS[family.name] if counter else "storage_bytes"
                identity = sha256(
                    json.dumps(
                        [metric, sorted(labels.items())], separators=(",", ":")
                    ).encode()
                ).hexdigest()
                point = MetricPoint(metric, labels, value)
                target = counters if counter else storage
                if identity in target:
                    raise failure()
                target[identity] = point
                if labels["capacity_mode"] != "serverless":
                    unsupported.add(point.group)
        if not counters or len(counters) + len(storage) > MAX_POINTS:
            raise failure(
                "metrics_missing",
                "Pinecone usage counters are unavailable; no usage or costs were inferred.",
            )
        return MetricSample(counters, storage, frozenset(unsupported))
    except (ValueError, InvalidOperation, TypeError, OverflowError):
        raise failure() from None


def _target(address, labels):
    if not isinstance(address, str) or not isinstance(labels, dict):
        raise failure(
            "unsafe_metrics_target",
            "Pinecone returned an unsupported monitoring target.",
        )
    parsed = urlsplit(address if "://" in address else "https://" + address)
    try:
        host, port = parsed.hostname, parsed.port
    except ValueError:
        raise failure("unsafe_metrics_target") from None
    if host:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise failure("unsafe_metrics_target")
    path = labels.get("__metrics_path__", "/metrics")
    if (
        parsed.scheme != "https"
        or labels.get("__scheme__", "https") != "https"
        or not host
        or not host.endswith(".pinecone.io")
        or not re.fullmatch(r"[a-z0-9.-]+", host)
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or not isinstance(path, str)
        or not re.fullmatch(r"/(?:[A-Za-z0-9._~-]+/)*metrics", path)
        or any(part in {".", ".."} for part in path.split("/"))
    ):
        raise failure(
            "unsafe_metrics_target",
            "Pinecone returned an unsupported monitoring target; no credentials were forwarded.",
        )
    return f"https://{host}{path}"


def _read(client, url, key, operation, deadline, limit):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise failure(
            "metrics_timeout", "Pinecone monitoring exceeded its collection deadline."
        )
    with billable_operation(
        "pinecone", operation, source="costs", sdk_retries=0
    ) as event:
        with client.stream(
            "GET",
            url,
            headers={"Authorization": "Bearer " + key},
            follow_redirects=False,
            timeout=min(10, remaining),
        ) as response:
            if not 200 <= response.status_code < 300:
                event.finish("failed", http_status=response.status_code)
                raise failure(
                    "metrics_access_denied"
                    if response.status_code in {401, 403}
                    else "metrics_unavailable",
                    "Pinecone metrics request failed; verify project ID, API key and monitoring access.",
                )
            body = bytearray()
            for chunk in response.iter_bytes():
                if time.monotonic() > deadline or len(body) + len(chunk) > limit:
                    raise failure(
                        "metrics_limit",
                        "Pinecone monitoring exceeded its response or time limit.",
                    )
                body.extend(chunk)
            return bytes(body)


def collect_metrics(project_id: str, api_key: str, *, client=None) -> MetricSample:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", project_id) or not api_key:
        raise ProviderFailure(
            "configuration_error", "Configure PINECONE_PROJECT_ID and PINECONE_API_KEY."
        )
    if client is None:
        from scripts.shared.automated_tests import automated_tests_enabled

        if automated_tests_enabled():
            raise ProviderFailure(
                "automated_test",
                "Live Pinecone metrics are disabled in automated tests.",
            )
        with httpx.Client(trust_env=False) as owned:
            return collect_metrics(project_id, api_key, client=owned)
    deadline = time.monotonic() + DEADLINE_SECONDS
    try:
        discovery = _read(
            client,
            f"https://api.pinecone.io/prometheus/projects/{project_id}/metrics/discovery",
            api_key,
            "metrics_discovery",
            deadline,
            256_000,
        )
        groups = json.loads(discovery)
        if not isinstance(groups, list) or not groups or len(groups) > MAX_TARGETS:
            raise failure()
        urls = set()
        for group in groups:
            if not isinstance(group, dict) or not isinstance(
                group.get("targets"), list
            ):
                raise failure()
            for address in group["targets"]:
                urls.add(_target(address, group.get("labels", {})))
                if len(urls) > MAX_TARGETS:
                    raise failure()
        if not urls:
            raise failure("metrics_missing", "Pinecone returned no monitoring targets.")
        counters, storage, unsupported = {}, {}, set()
        remaining = MAX_TOTAL - len(discovery)
        for url in sorted(urls):
            body = _read(
                client,
                url,
                api_key,
                "metrics_scrape",
                deadline,
                min(MAX_RESPONSE, remaining),
            )
            remaining -= len(body)
            sample = parse_metrics(body.decode("utf-8"))
            for target, incoming in (
                (counters, sample.counters),
                (storage, sample.storage),
            ):
                for identity, point in incoming.items():
                    if identity in target and target[identity] != point:
                        raise failure()
                    target[identity] = point
            unsupported.update(sample.unsupported)
            if len(counters) + len(storage) > MAX_POINTS:
                raise failure(
                    "metrics_limit",
                    "Pinecone monitoring exceeded its metric series limit.",
                )
        return MetricSample(counters, storage, frozenset(unsupported))
    except (httpx.HTTPError, ValueError, UnicodeError, TypeError):
        raise failure(
            "metrics_unavailable",
            "Pinecone metrics could not be read; verify configuration and monitoring access.",
        ) from None

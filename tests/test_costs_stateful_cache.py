from datetime import timedelta
import json

import pytest

from services.costs import contracts
from services.costs.cache import SnapshotCache
from services.costs.contracts import ProviderFailure
from tests.test_costs import NOW, report


def cache(tmp_path):
    return SnapshotCache(
        tmp_path,
        "pinecone",
        "project:test",
        success_interval=timedelta(minutes=5),
        failure_interval=timedelta(minutes=5),
        daily_attempt_limit=288,
    )


def pinecone_report(total=None):
    return report().model_copy(update={"provider": "pinecone", "total": total})


def test_stateful_cache_persists_baseline_across_restart_and_keeps_it_private(tmp_path):
    calls = []

    def baseline(previous_report, previous_state):
        assert previous_report is None and previous_state is None
        calls.append(1)
        return contracts.CollectionResult(pinecone_report(), {"counter": "10"})

    first = cache(tmp_path).read_or_collect(NOW, baseline)
    assert first["report"]["total"] is None
    assert "counter" not in json.dumps(first)
    assert json.loads(next(tmp_path.glob("*.json")).read_text())["state"] == {
        "counter": "10"
    }
    for second in (15, 30, 299):
        assert (
            cache(tmp_path).read_or_collect(
                NOW + timedelta(seconds=second),
                lambda *_: pytest.fail("UI polling collected metrics"),
            )["state"]
            == "ready"
        )

    def changed(previous_report, previous_state):
        assert previous_report.total is None
        assert previous_state == {"counter": "10"}
        return contracts.CollectionResult(pinecone_report("0.25"), {"counter": "12"})

    assert (
        cache(tmp_path).read_or_collect(NOW + timedelta(minutes=5), changed)["report"][
            "total"
        ]
        == "0.25"
    )
    assert calls == [1]
    assert json.loads(next(tmp_path.glob("*.json")).read_text())["state"] == {
        "counter": "12"
    }


def test_failed_collector_cannot_mutate_preserved_report_or_counter_state(tmp_path):
    subject = cache(tmp_path)
    subject.read_or_collect(
        NOW,
        lambda *_: contracts.CollectionResult(
            pinecone_report("1"), {"counter": ["10"]}
        ),
    )

    def failure(previous_report, previous_state):
        previous_report.total = "PRIVATE_BAD_VALUE"
        previous_state["counter"].append("PRIVATE_BAD_VALUE")
        raise ProviderFailure("unavailable", "Metrics temporarily unavailable.")

    result = subject.read_or_collect(NOW + timedelta(minutes=5), failure)
    assert result["state"] == "stale"
    assert result["report"]["total"] == "1"
    persisted = json.loads(subject.path.read_text())
    assert persisted["state"] == {"counter": ["10"]}
    assert "PRIVATE_BAD_VALUE" not in subject.path.read_text()
    assert result["error"]["code"] == "unavailable"


def test_interrupted_collection_persists_attempt_and_previous_state(tmp_path):
    subject = cache(tmp_path)
    subject.read_or_collect(
        NOW,
        lambda *_: contracts.CollectionResult(pinecone_report("1"), {"counter": "10"}),
    )

    def interrupted(previous_report, previous_state):
        assert previous_state == {"counter": "10"}
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        subject.read_or_collect(NOW + timedelta(minutes=5), interrupted)
    assert json.loads(subject.path.read_text())["state"] == {"counter": "10"}
    assert (
        cache(tmp_path).read_or_collect(
            NOW + timedelta(minutes=6),
            lambda *_: pytest.fail("restart bypassed backoff"),
        )["error"]["code"]
        == "interrupted_refresh"
    )


@pytest.mark.parametrize(
    "invalid", [[], {"counter": float("nan")}, {"counter": object()}]
)
def test_invalid_private_state_cannot_replace_valid_baseline(tmp_path, invalid):
    subject = cache(tmp_path)
    subject.read_or_collect(
        NOW,
        lambda *_: contracts.CollectionResult(pinecone_report("1"), {"counter": "10"}),
    )
    result = subject.read_or_collect(
        NOW + timedelta(minutes=5),
        lambda *_: contracts.CollectionResult(pinecone_report("2"), invalid),
    )
    assert result["state"] == "stale"
    assert result["report"]["total"] == "1"
    assert json.loads(subject.path.read_text())["state"] == {"counter": "10"}

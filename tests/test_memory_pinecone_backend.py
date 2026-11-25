from __future__ import annotations

from types import SimpleNamespace

import pytest
from pinecone.core.openapi.db_data.model.fetch_response import FetchResponse
from pinecone.core.openapi.db_data.model.list_item import ListItem
from pinecone.core.openapi.db_data.model.list_response import ListResponse
from pinecone.core.openapi.db_data.model.pagination import Pagination
from pinecone.core.openapi.db_data.model.vector import Vector

import services.memory.backends.pinecone_backend as pinecone_backend


def page(ids, next_token=None):
    result = {"vectors": [{"id": id} for id in ids], "usage": {"read_units": 1}}
    if next_token is not None:
        result["pagination"] = {"next": next_token}
    return result


class _FakeIndex:
    def __init__(self, pages, *, missing=()):
        self.pages = pages
        self.missing = set(missing)
        self.list_calls = []
        self.fetch_calls = []

    def query(self, **kwargs):
        raise AssertionError(
            "Complete memory enumeration must not use similarity queries"
        )

    def list_paginated(self, **kwargs):
        self.list_calls.append(kwargs)
        return self.pages[kwargs["pagination_token"]]

    def fetch(self, ids, **kwargs):
        self.fetch_calls.append((ids, kwargs))
        return {
            "vectors": {
                id: {"metadata": {"text": f"memory {id}", "repo": "synthetic"}}
                for id in reversed(ids)
                if id not in self.missing
            },
            "usage": {"read_units": 2},
        }


def install(monkeypatch, index):
    monkeypatch.setattr(pinecone_backend, "_get_index", lambda: index)


def test_load_all_enumerates_more_than_ten_thousand_records_without_querying(
    monkeypatch,
):
    ids = [f"m{number:05d}" for number in range(10001)]
    pages = {}
    for start in range(0, len(ids), 100):
        token = None if start == 0 else f"page-{start}"
        next_start = start + 100
        pages[token] = page(
            ids[start:next_start],
            f"page-{next_start}" if next_start < len(ids) else None,
        )
    index = _FakeIndex(pages)
    install(monkeypatch, index)

    rows = pinecone_backend.load_all()

    assert [row["id"] for row in rows] == ids
    assert rows[-1] == {
        "id": ids[-1],
        "text": f"memory {ids[-1]}",
        "metadata": {"repo": "synthetic"},
    }
    assert len(index.list_calls) == len(index.fetch_calls) == 101
    assert [call["pagination_token"] for call in index.list_calls] == list(pages)
    assert all(
        call["limit"] == 100 and 0 < call["_request_timeout"] <= 10
        for call in index.list_calls
    )
    assert all(
        len(batch) <= 1000 and 0 < kwargs["_request_timeout"] <= 10
        for batch, kwargs in index.fetch_calls
    )
    assert all("namespace" not in call for call in index.list_calls)


def test_load_all_accepts_real_sdk_models_and_canonicalizes_metadata(monkeypatch):
    index = _FakeIndex(
        {
            None: ListResponse(
                vectors=[ListItem(id="first")], pagination=Pagination(next="next-page")
            ),
            "next-page": ListResponse(vectors=[ListItem(id="second")]),
        }
    )

    def fetch(ids, **kwargs):
        return FetchResponse(
            vectors={
                id: Vector(
                    id=id,
                    values=[0.5],
                    metadata={
                        "text": f"memory {id}",
                        "last_accessed_at": "2026-01-01T07:00:00-05:00",
                    },
                )
                for id in ids
            }
        )

    monkeypatch.setattr(index, "fetch", fetch)
    install(monkeypatch, index)

    rows = pinecone_backend.load_all()

    assert [row["id"] for row in rows] == ["first", "second"]
    assert rows[0]["metadata"] == {"last_accessed_at": "2026-01-01T12:00:00+00:00"}
    assert rows[0]["text"] == "memory first"


def test_load_all_empty_index_does_not_fetch(monkeypatch):
    index = _FakeIndex({None: page([])})
    install(monkeypatch, index)

    assert pinecone_backend.load_all() == []
    assert len(index.list_calls) == 1
    assert index.fetch_calls == []


def test_load_all_follows_cursor_after_short_and_empty_pages(monkeypatch):
    index = _FakeIndex(
        {
            None: page(["first"], "empty-page"),
            "empty-page": page([], "last-page"),
            "last-page": page(["last"]),
        }
    )
    install(monkeypatch, index)

    assert [row["id"] for row in pinecone_backend.load_all()] == ["first", "last"]
    assert [call["pagination_token"] for call in index.list_calls] == [
        None,
        "empty-page",
        "last-page",
    ]
    assert [ids for ids, _ in index.fetch_calls] == [["first"], ["last"]]


def test_load_all_deduplicates_in_provider_order_and_omits_concurrent_deletions(
    monkeypatch,
):
    index = _FakeIndex(
        {
            None: page(["first", "first", "deleted", "second"], "last-page"),
            "last-page": page(["second", "third"]),
        },
        missing={"deleted"},
    )
    install(monkeypatch, index)

    assert [row["id"] for row in pinecone_backend.load_all()] == [
        "first",
        "second",
        "third",
    ]
    assert [ids for ids, _ in index.fetch_calls] == [
        ["first", "deleted", "second"],
        ["third"],
    ]


def test_load_all_rejects_cursor_cycles_before_fetching_repeated_page(monkeypatch):
    index = _FakeIndex(
        {
            None: page(["first"], "page-two"),
            "page-two": page(["second"], "page-three"),
            "page-three": page(["third"], "page-two"),
        }
    )
    install(monkeypatch, index)

    with pytest.raises(RuntimeError, match="page 3 repeated a continuation token"):
        pinecone_backend.load_all()

    assert len(index.list_calls) == 3
    assert len(index.fetch_calls) == 2


@pytest.mark.parametrize(
    "result",
    [
        None,
        {"vectors": None},
        {"vectors": "invalid"},
        page(["id"] * 101),
        {"vectors": [{}]},
        page([None]),
        page([123]),
        page([""]),
        page([" "]),
        {"vectors": [], "pagination": 123},
        page([], 123),
        page([], ""),
        page([], " "),
    ],
)
def test_load_all_rejects_malformed_pages_before_fetch(monkeypatch, result):
    index = _FakeIndex({None: result})
    install(monkeypatch, index)

    with pytest.raises(RuntimeError, match="Pinecone memory enumeration page 1"):
        pinecone_backend.load_all()

    assert index.fetch_calls == []


@pytest.mark.parametrize("stage", ["list", "fetch"])
def test_load_all_preserves_provider_errors_with_page_diagnostics(monkeypatch, stage):
    index = _FakeIndex(
        {None: page(["first"], "page-two"), "page-two": page(["second"])}
    )
    error = RuntimeError(f"Synthetic provider {stage} failure")
    method = getattr(index, "list_paginated" if stage == "list" else "fetch")

    def fail_second(*args, **kwargs):
        if kwargs.get("pagination_token") == "page-two" or kwargs.get("ids") == [
            "second"
        ]:
            raise error
        return method(*args, **kwargs)

    monkeypatch.setattr(
        index, "list_paginated" if stage == "list" else "fetch", fail_second
    )
    install(monkeypatch, index)

    with pytest.raises(RuntimeError) as raised:
        pinecone_backend.load_all()

    assert raised.value is error
    expected_pages = 1 if stage == "list" else 2
    assert raised.value.__notes__ == [
        f"Pinecone memory enumeration failed during {stage} after {expected_pages} pages and 1 rows"
    ]


def test_load_all_deadline_prevents_another_provider_request(monkeypatch):
    index = _FakeIndex({None: page(["first"])})
    clock = iter([0.0, 121.0])
    monkeypatch.setattr(
        pinecone_backend, "time", SimpleNamespace(monotonic=lambda: next(clock))
    )
    install(monkeypatch, index)

    with pytest.raises(
        TimeoutError, match="during list after 0 pages and 0 rows.*120-second"
    ):
        pinecone_backend.load_all()

    assert index.list_calls == index.fetch_calls == []


def test_load_all_passes_remaining_overall_budget_to_fetch(monkeypatch):
    index = _FakeIndex({None: page(["first"])})
    clock = [0.0]
    original = index.list_paginated

    def list_near_deadline(**kwargs):
        result = original(**kwargs)
        clock[0] = 115.0
        return result

    monkeypatch.setattr(index, "list_paginated", list_near_deadline)
    monkeypatch.setattr(
        pinecone_backend, "time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    install(monkeypatch, index)

    assert len(pinecone_backend.load_all()) == 1
    assert index.list_calls[0]["_request_timeout"] == 10
    assert index.fetch_calls[0][1]["_request_timeout"] == 5


def test_load_all_checks_deadline_after_fetch_before_returning_rows(monkeypatch):
    index = _FakeIndex({None: page(["first"])})
    clock = [0.0]
    original = index.fetch

    def slow_fetch(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] = 121.0
        return result

    monkeypatch.setattr(index, "fetch", slow_fetch)
    monkeypatch.setattr(
        pinecone_backend, "time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    install(monkeypatch, index)

    with pytest.raises(
        TimeoutError, match="during fetch after 1 pages and 1 rows.*120-second"
    ):
        pinecone_backend.load_all()


def test_load_all_observes_every_list_and_fetch_operation(monkeypatch):
    events = []

    def start(provider, operation, **metadata):
        event = {"provider": provider, "operation": operation, "metadata": metadata}
        events.append(event)
        return SimpleNamespace(finish=lambda **usage: event.update(usage))

    monkeypatch.setattr(pinecone_backend.BillableEvent, "start", start)
    raw = _FakeIndex({None: page(["first"], "page-two"), "page-two": page(["second"])})
    install(
        monkeypatch, pinecone_backend._ObservedPinecone(raw, index="synthetic-index")
    )

    assert len(pinecone_backend.load_all()) == 2
    assert [event["operation"] for event in events] == [
        "list_paginated",
        "fetch",
        "list_paginated",
        "fetch",
    ]
    assert [event["read_units"] for event in events] == [1, 2, 1, 2]
    assert all(event["provider"] == "pinecone" for event in events)
    assert all(
        event["metadata"]["index"] == "synthetic-index"
        and event["metadata"]["namespace"] == ""
        for event in events
    )

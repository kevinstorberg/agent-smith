import asyncio
from concurrent.futures import CancelledError, Future
from copy import deepcopy
from datetime import datetime, timezone
from multiprocessing import TimeoutError as PoolTimeoutError
from multiprocessing.pool import ThreadPool
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
import pytest

from services.memory.backends import pinecone_backend as pb
from services.observability import current_trigger, trigger_context
from tests.test_memory_access_backends import PineconeRecords


def records(caplog):
    return [record.billable_event for record in caplog.records if hasattr(record, "billable_event")]


def proxy_with(method, result, caplog):
    def call(*args, **kwargs):
        assert records(caplog)[-1]["phase"] == "START"
        return result

    return pb._ObservedPinecone(SimpleNamespace(**{method: call}), index="synthetic-index")


def test_real_backend_initialization_wraps_control_and_data_and_keeps_config(monkeypatch, caplog):
    monkeypatch.setattr(pb, "_pc", None)
    monkeypatch.setattr(pb, "_index", None)
    monkeypatch.setenv("PINECONE_API_KEY", "PRIVATE_KEY")
    config = SimpleNamespace(host="PRIVATE_HOST", api_key="PRIVATE_KEY")

    def observed(result):
        def call(*_, **__):
            assert records(caplog)[-1]["phase"] == "START"
            return result
        return call

    pc = SimpleNamespace(has_index=observed(False), create_index=observed(None), describe_index=observed(SimpleNamespace(host="PRIVATE_HOST", status={"ready": True})))
    raw = SimpleNamespace(config=config, fetch=observed({"vectors": {}, "usage": {"read_units": 2}}))
    monkeypatch.setattr(pb, "Pinecone", lambda **_: pc)
    constructions = []

    def index(**kwargs):
        constructions.append(kwargs)
        return raw

    monkeypatch.setattr(pb, "Index", index)
    with trigger_context(trigger="mcp", tool="memory", request_id="synthetic"):
        assert pb.get_row(str(uuid4())) is None

    assert pb._index.config is config
    assert constructions[0]["openapi_config"].retries == 0
    events = records(caplog)
    assert [event["operation"] for event in events[::2]] == ["has_index", "create_index", "describe_index", "describe_index", "fetch"]
    assert events[-1]["read_units"] == 2
    for before, after in zip(events[::2], events[1::2]):
        assert before["event_id"] == after["event_id"] and after["outcome"] == "success"
        assert before["trigger"] == "mcp" and before["index"] == pb.INDEX_NAME
    assert "PRIVATE_" not in caplog.text and current_trigger() == {}


@pytest.mark.parametrize("method,kwargs,count", [
    ("fetch", {"ids": ["PRIVATE_ID", "PRIVATE_ID2"]}, 2),
    ("delete", {"ids": ["PRIVATE_ID"]}, 1),
    ("update", {"id": "PRIVATE_ID", "set_metadata": {"text": "PRIVATE_TEXT"}}, 1),
    ("upsert", {"vectors": [("PRIVATE_ID", [0.1], {"text": "PRIVATE_TEXT"})]}, 1),
    ("query", {"vector": [0.1], "top_k": 5, "filter": {"text": "PRIVATE_TEXT"}}, 5),
])
def test_data_proxy_preserves_arguments_result_and_safe_metadata(caplog, method, kwargs, count):
    response = {"usage": {"read_units": 3, "write_units": 4}, "PRIVATE_RESULT": "PRIVATE_TEXT"}
    captured = []

    def call(*args, **values):
        assert len(records(caplog)) == 1
        captured.append((args, values))
        return response

    proxy = pb._ObservedPinecone(SimpleNamespace(**{method: call}), index="synthetic-index")
    kwargs.update(namespace="synthetic-namespace", _request_timeout=2)
    original = deepcopy(kwargs)
    assert getattr(proxy, method)(**kwargs) is response
    assert captured == [((), original)] and kwargs == original
    before, after = records(caplog)
    assert (before["provider"], before["operation"], before["count"], before["namespace"]) == ("pinecone", method, count, "synthetic-namespace")
    assert before["sdk_retries"] == 0 and (after["read_units"], after["write_units"]) == (3, 4)
    assert before["event_id"] == after["event_id"] and "PRIVATE_" not in caplog.text


@pytest.mark.parametrize("value", [True, -1, 1.5, "PRIVATE_UNIT", {"PRIVATE_UNIT": 3}, None])
def test_usage_logs_only_actual_nonnegative_integer_counters(caplog, value):
    proxy = proxy_with("query", SimpleNamespace(usage=SimpleNamespace(read_units=value, write_units=value)), caplog)
    proxy.query(vector=[0.1], top_k=1)
    assert not {"read_units", "write_units"} & records(caplog)[-1].keys()
    assert "PRIVATE_" not in caplog.text


def test_sdk_apply_result_wait_timeout_is_nonterminal_and_cause_is_frozen(caplog):
    release = Event()
    response = {"usage": {"write_units": 7}}
    with ThreadPool(1) as pool:
        def deferred(**_):
            assert len(records(caplog)) == 1
            return pool.apply_async(lambda: (release.wait(2), response)[1])

        proxy = pb._ObservedPinecone(SimpleNamespace(upsert=deferred), index="synthetic-index")
        try:
            with trigger_context(trigger="job", job_id=12, reason="scheduled_interval"):
                result = proxy.upsert(vectors=[("PRIVATE_ID", [0.1])], async_req=True)
            assert len(records(caplog)) == 1 and not result.ready()
            with trigger_context(trigger="mcp", request_id="other"):
                with pytest.raises(PoolTimeoutError):
                    result.get(timeout=0)
                assert len(records(caplog)) == 1
                release.set()
                assert result.get(timeout=2) is response
                assert result.get(timeout=0) is response
        finally:
            release.set()
    before, after = records(caplog)
    assert before["event_id"] == after["event_id"] and after["outcome"] == "success"
    assert after["trigger"] == "job" and after["job_id"] == 12 and after["reason"] == "scheduled_interval"
    assert after["write_units"] == 7 and "request_id" not in after and "PRIVATE_" not in caplog.text


@pytest.mark.parametrize("kind,outcome", [(RuntimeError, "failed"), (TimeoutError, "timeout"), (PoolTimeoutError, "failed")])
def test_apply_result_terminal_sdk_error_is_distinguished_from_wait_timeout(caplog, kind, outcome):
    failure = kind("PRIVATE_ERROR")
    with ThreadPool(1) as pool:
        def fail():
            raise failure

        result = proxy_with("upsert", pool.apply_async(fail), caplog).upsert(vectors=[], async_req=True)
        with pytest.raises(kind) as raised:
            result.get(timeout=2)
        assert raised.value is failure
        with pytest.raises(kind):
            result.get(timeout=0)
    before, after = records(caplog)
    assert before["event_id"] == after["event_id"] and after["outcome"] == outcome
    assert after["error_type"] == kind.__name__ and "PRIVATE_" not in caplog.text


def test_concurrent_future_wait_timeout_and_duplicate_result_preserve_terminal_pair(caplog):
    future = Future()
    result = proxy_with("query", future, caplog).query(top_k=1, vector=[0.1], async_threadpool_executor=True)
    with pytest.raises(TimeoutError):
        result.result(timeout=0)
    assert len(records(caplog)) == 1
    response = SimpleNamespace(usage=SimpleNamespace(read_units=9))
    future.set_result(response)
    assert result.result(timeout=0) is response and result.result(timeout=0) is response
    assert len(records(caplog)) == 2 and records(caplog)[-1]["read_units"] == 9


def test_wait_timeout_race_with_success_does_not_log_false_terminal_failure(caplog):
    class RacingFuture(Future):
        first = True

        def result(self, timeout=None):
            if self.first:
                self.first = False
                self.set_result("PRIVATE_RESULT")
                raise TimeoutError("PRIVATE_WAIT_TIMEOUT")
            return super().result(timeout=timeout)

    result = proxy_with("query", RacingFuture(), caplog).query(top_k=1, vector=[0.1], async_threadpool_executor=True)
    with pytest.raises(TimeoutError):
        result.result(timeout=0)
    assert len(records(caplog)) == 1
    assert result.result(timeout=0) == "PRIVATE_RESULT"
    assert records(caplog)[-1]["outcome"] == "success" and "PRIVATE_" not in caplog.text


@pytest.mark.parametrize("kind,outcome", [(RuntimeError, "failed"), (TimeoutError, "timeout"), (asyncio.CancelledError, "cancelled"), (KeyboardInterrupt, "cancelled")])
def test_concurrent_future_terminal_errors_keep_identity(caplog, kind, outcome):
    future = Future()
    failure = kind("PRIVATE_ERROR")
    future.set_exception(failure)
    result = proxy_with("query", future, caplog).query(top_k=1, vector=[0.1], async_threadpool_executor=True)
    with pytest.raises(kind) as raised:
        result.result(timeout=0)
    assert raised.value is failure
    before, after = records(caplog)
    assert before["event_id"] == after["event_id"] and after["outcome"] == outcome
    assert "PRIVATE_" not in caplog.text


def test_cancelled_future_records_terminal_cancellation(caplog):
    future = Future()
    result = proxy_with("query", future, caplog).query(top_k=1, vector=[0.1], async_threadpool_executor=True)
    assert result.cancel()
    with pytest.raises(CancelledError):
        result.result(timeout=0)
    assert len(records(caplog)) == 2 and records(caplog)[-1]["outcome"] == "cancelled"


class ScriptedEmbeddings(Embeddings):
    def embed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0]


def test_actual_inherited_langchain_query_and_async_upsert_traverse_proxy(monkeypatch, caplog):
    id = str(uuid4())
    calls = []

    def query(**kwargs):
        assert records(caplog)[-1]["phase"] == "START"
        calls.append(("query", kwargs))
        return {"matches": [{"id": id, "score": 0.8, "metadata": {"text": "PRIVATE_CONTENT", "repo": "synthetic"}}], "usage": {"read_units": 1}}

    def fetch(**kwargs):
        calls.append(("fetch", kwargs))
        return {"vectors": {}}

    pool = ThreadPool(1)

    def upsert(**kwargs):
        assert records(caplog)[-1]["phase"] == "START"
        calls.append(("upsert", kwargs))
        return pool.apply_async(lambda: {"upserted_count": 1})

    raw = SimpleNamespace(config=SimpleNamespace(host="PRIVATE_HOST", api_key="PRIVATE_KEY"), query=query, fetch=fetch, upsert=upsert)
    proxy = pb._ObservedPinecone(raw, index="synthetic-index")
    monkeypatch.setattr(pb, "_get_index", lambda: proxy)
    store = pb.get_vectorstore(ScriptedEmbeddings())
    assert store.index is proxy and store._index_host == "PRIVATE_HOST"
    assert store.similarity_search_with_score("PRIVATE_QUERY", k=3)[0][0].page_content == "PRIVATE_CONTENT"
    try:
        assert store.add_documents([Document(page_content="PRIVATE_CONTENT", metadata={"id": id})], ids=[id]) == [id]
    finally:
        pool.close()
        pool.join()
    assert [name for name, _ in calls] == ["query", "fetch", "upsert"]
    assert calls[-1][1]["async_req"] is True
    assert [event["operation"] for event in records(caplog)[::2]] == ["query", "fetch", "upsert"]
    assert len(records(caplog)) == 6 and all(event["outcome"] == "success" for event in records(caplog)[1::2])
    assert "PRIVATE_" not in caplog.text


def test_touch_executor_workers_keep_trigger_and_unchanged_update_contract(monkeypatch, caplog):
    raw = PineconeRecords(3)
    original_update = raw.update

    def update(**kwargs):
        assert current_trigger()["request_id"] == "synthetic"
        return original_update(**kwargs)

    raw.update = update
    proxy = pb._ObservedPinecone(raw, index="synthetic-index")
    monkeypatch.setattr(pb, "_get_index", lambda: proxy)
    stamp = datetime(2027, 1, 1, tzinfo=timezone.utc)
    before = deepcopy(raw.records)
    with trigger_context(trigger="mcp", tool="memory", request_id="synthetic"):
        assert pb.touch_accessed(list(raw.records), stamp) == dict.fromkeys(raw.records, stamp.isoformat())
    events = records(caplog)
    assert len(events) == 8 and all(event["request_id"] == "synthetic" for event in events)
    for id, row in raw.records.items():
        assert row["values"] == before[id]["values"]
        assert row["metadata"] == before[id]["metadata"] | {"last_accessed_at": stamp.isoformat()}
    assert all(kwargs["_request_timeout"] <= 10 for _, _, kwargs in raw.updates)
    assert current_trigger() == {} and "Keep Python" not in caplog.text

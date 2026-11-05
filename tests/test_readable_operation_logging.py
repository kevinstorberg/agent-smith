import asyncio
import logging

import pytest

from services import observability


def messages(caplog, level=logging.INFO):
    return [record.getMessage() for record in caplog.records if record.levelno == level]


@pytest.mark.parametrize(
    "provider,operation,prefix",
    [
        ("bedrock", "chat_completion", "MODEL GENERATE [BILLABLE]"),
        ("pinecone", "query", "PINECONE QUERY [BILLABLE]"),
        ("granola", "list_notes", "GRANOLA LIST NOTES [BILLABLE]"),
        ("command", "subprocess", "COMMAND RUN [BILLABLE?]"),
    ],
)
def test_one_readable_provider_entry_precedes_call_without_routine_terminal_info(
    caplog, provider, operation, prefix
):
    caplog.set_level(logging.INFO, logger="agent_smith.billable")
    with observability.trigger_context(
        trigger="job.manual", job_id=7, request_id="captured"
    ):
        with observability.billable_operation(provider, operation) as event:
            assert len(messages(caplog)) == 1
            assert messages(caplog)[0].startswith(prefix + " ")
            assert event.event_id in messages(caplog)[0]
    assert len(messages(caplog)) == 1
    assert "BILLABLE START" not in caplog.text and "BILLABLE END" not in caplog.text


def test_terminal_diagnostics_keep_usage_and_snapshot_at_debug(caplog):
    caplog.set_level(logging.DEBUG, logger="agent_smith.billable")
    with observability.trigger_context(trigger="manual", request_id="original"):
        event = observability.BillableEvent.start("bedrock", "chat_completion")
    with observability.trigger_context(request_id="later"):
        assert event.finish(tokens_input=3, tokens_output=5)
        assert not event.finish()
    start, terminal = [
        r.billable_event for r in caplog.records if hasattr(r, "billable_event")
    ]
    assert start["event_id"] == terminal["event_id"]
    assert terminal["request_id"] == "original"
    assert terminal["tokens_input"] == 3 and terminal["tokens_output"] == 5
    assert terminal["outcome"] == "success"
    assert len(messages(caplog)) == len(messages(caplog, logging.DEBUG)) == 1
    assert messages(caplog, logging.DEBUG)[0].startswith("MODEL GENERATE [BILLABLE] ")


@pytest.mark.parametrize(
    "resource,action,backend,prefix",
    [
        ("memory", "search", "pinecone", "MEMORY SEARCH [BILLABLE]"),
        ("memory", "search", "lancedb", "MEMORY SEARCH [NONBILLABLE]"),
        ("memory", "search", "pgvector", "MEMORY SEARCH [NONBILLABLE]"),
        ("action-items", "create", "pinecone", "ACTION ITEM CREATE [NONBILLABLE]"),
        ("jobs", "run", "lancedb", "JOB RUN [BILLABLE?]"),
        ("future", "transmit", "lancedb", "TOOL TRANSMIT [BILLABLE?]"),
    ],
)
def test_logical_action_classification_is_explicit(
    caplog, monkeypatch, resource, action, backend, prefix
):
    monkeypatch.setenv("MEMORY_BACKEND", backend)
    caplog.set_level(logging.INFO, logger="agent_smith.action")
    with observability.action_operation(resource, action, owner="test"):
        assert messages(caplog)[0].startswith(prefix + " ")
    assert len(messages(caplog)) == 1


def test_same_action_adapters_deduplicate_but_real_provider_calls_do_not(
    caplog, monkeypatch
):
    monkeypatch.setenv("MEMORY_BACKEND", "pinecone")
    caplog.set_level(logging.INFO)
    with observability.trigger_context(request_id="same-request"):
        with observability.action_operation("memory", "search", owner="http"):
            with observability.action_operation("memory", "search", owner="mcp"):
                for _ in range(2):
                    with observability.billable_operation("pinecone", "query"):
                        pass
    lines = messages(caplog)
    assert sum(line.startswith("MEMORY SEARCH [BILLABLE]") for line in lines) == 1
    assert sum(line.startswith("PINECONE QUERY [BILLABLE]") for line in lines) == 2


def test_distinct_nested_calls_from_same_boundary_are_not_suppressed(caplog):
    caplog.set_level(logging.INFO)
    with observability.action_operation(
        "graphs", "run", owner="graph", graph="opinion"
    ):
        with observability.action_operation("graphs", "run", owner="graph"):
            pass
    assert (
        sum(line.startswith("GRAPH RUN [BILLABLE]") for line in messages(caplog)) == 2
    )


def test_a_new_nested_adapter_call_is_not_hidden_by_its_parent_execution(caplog):
    caplog.set_level(logging.INFO)
    with observability.action_operation(
        "graphs", "run", owner="graph", graph="opinion"
    ):
        with observability.action_operation("graphs", "run", owner="mcp"):
            with observability.action_operation("graphs", "run", owner="graph"):
                pass
    assert (
        sum(line.startswith("GRAPH RUN [BILLABLE]") for line in messages(caplog)) == 2
    )


def test_memory_backend_snapshot_matches_actual_backend_dispatch(caplog, monkeypatch):
    from services.memory.backends import get_backend

    monkeypatch.setenv("MEMORY_BACKEND", "lancedb")
    caplog.set_level(logging.INFO)
    with observability.action_operation("memory", "search", owner="mcp"):
        monkeypatch.setenv("MEMORY_BACKEND", "pinecone")
        assert get_backend().__name__.endswith("lancedb_backend")
    assert messages(caplog)[0].startswith("MEMORY SEARCH [NONBILLABLE]")
    assert get_backend().__name__.endswith("pinecone_backend")


def test_unknown_untrusted_action_cannot_forge_lines_or_reveal_payload(caplog):
    caplog.set_level(logging.INFO)
    with observability.action_operation(
        "unknown\nPRIVATE_TOKEN", "https://secret/?key=PRIVATE_TOKEN", owner="test"
    ):
        pass
    assert len(messages(caplog)) == 1
    assert messages(caplog)[0].startswith("TOOL CALL [BILLABLE?]")
    assert "PRIVATE_TOKEN" not in caplog.text


@pytest.mark.asyncio
async def test_cancelled_action_preserves_exception_and_restores_scopes(caplog):
    error = asyncio.CancelledError("PRIVATE_CANCELLATION")
    baseline = observability.current_trigger()
    with pytest.raises(asyncio.CancelledError) as caught:
        with observability.action_operation("graphs", "run", owner="graph"):
            raise error
    assert caught.value is error
    assert observability.current_trigger() == baseline
    assert "PRIVATE_CANCELLATION" not in caplog.text

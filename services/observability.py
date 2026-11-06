from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping
from concurrent.futures import CancelledError as FutureCancelledError, Executor, Future
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar, copy_context
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
import json
import logging
import math
import re
from threading import Lock
import time
from types import MappingProxyType
from typing import Any, Callable, TypeVar
from uuid import UUID, uuid4

from scripts.shared.operation_logging import (
    action_label,
    provider_label,
    resource_name,
    write_log as _write_log,
)
from scripts.shared.tool_logging import ToolInvocation


logger = logging.getLogger("agent_smith.billable")
_work_logger = logging.getLogger("agent_smith.work")
_action_logger = logging.getLogger("agent_smith.action")
for _logger in (logger, _work_logger, _action_logger):
    if _logger.level == logging.NOTSET:
        _logger.setLevel(logging.INFO)
_trigger: ContextVar[Mapping[str, Any] | None] = ContextVar(
    "billable_trigger", default=None
)
_actions: ContextVar[tuple[_ActionFrame, ...]] = ContextVar(
    "action_boundaries", default=()
)
_ADAPTER_OWNERS = frozenset({"http", "mcp", "agent_tool"})
_CONTEXT_FIELDS = frozenset(
    {
        "trigger",
        "origin",
        "request_id",
        "client",
        "tool",
        "agent_tool",
        "graph",
        "graph_run_id",
        "job_id",
        "execution_id",
        "meeting_id",
        "profile_id",
        "source",
        "source_kind",
        "source_hash",
        "source_revision",
        "stage",
        "stage_status",
        "reason",
        "attempt",
        "manual_request_id",
        "requested_at",
        "checkpoint",
        "model_role",
        "model",
        "sdk_retries",
        "index",
        "namespace",
        "parent_event_id",
        "model_run_id",
        "parent_model_run_id",
        "count",
        "streaming",
        "billing",
        "input_messages",
        "input_characters",
        "memory_backend",
    }
)
_END_FIELDS = frozenset(
    {
        "http_status",
        "exit_code",
        "tokens_input",
        "tokens_output",
        "total_tokens",
        "read_units",
        "write_units",
        "finish_reason",
        "completion",
    }
)
_OUTCOMES = frozenset({"success", "failed", "cancelled", "timeout", "unknown"})
_TIMEOUT_TYPES = frozenset(
    {
        ("httpx", "TimeoutException"),
        ("openai", "APITimeoutError"),
        ("anthropic", "APITimeoutError"),
        ("urllib3.exceptions", "TimeoutError"),
        ("botocore.exceptions", "ConnectTimeoutError"),
        ("botocore.exceptions", "ReadTimeoutError"),
        ("google.api_core.exceptions", "DeadlineExceeded"),
    }
)
_T = TypeVar("_T")


@dataclass(frozen=True)
class _ActionFrame:
    resource: str
    action: str
    owner: str
    request_id: str | None
    event: BillableEvent


def _safe_fields(fields: Mapping[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    unexpected = fields.keys() - allowed
    if unexpected:
        raise ValueError(
            "Unsupported billable log fields: " + ", ".join(sorted(unexpected))
        )
    result = {}
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, UUID):
            value = str(value)
        elif isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"Billable log field {key!r} must include a timezone")
            value = value.astimezone(timezone.utc).isoformat()
        if isinstance(value, str):
            value = value[:512]
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError(f"Billable log field {key!r} must be finite")
        elif not isinstance(value, (int, bool)):
            raise ValueError(f"Billable log field {key!r} must be a scalar")
        result[key] = value
    return result


def current_trigger() -> dict[str, Any]:
    return dict(_trigger.get() or {})


@contextmanager
def trigger_context(**fields: Any) -> Iterator[None]:
    values = {**current_trigger(), **_safe_fields(fields, _CONTEXT_FIELDS)}
    token = _trigger.set(MappingProxyType(values))
    try:
        yield
    finally:
        _trigger.reset(token)


def _event_level(record: dict[str, Any]) -> int:
    if record["phase"] == "START":
        return logging.INFO
    return (
        logging.WARNING
        if record.get("outcome") in {"failed", "timeout"}
        else logging.DEBUG
    )


def _emit(record: dict[str, Any]) -> None:
    label = provider_label(record["provider"], record["operation"])
    _write_log(
        record, label.prefix, logger, "billable_event", level=_event_level(record)
    )


def work_decision(decision: str, **fields: Any) -> None:
    if not isinstance(decision, str) or not re.fullmatch(
        r"[a-z][a-z0-9_]{0,63}", decision
    ):
        raise ValueError("Work decision must be a short lowercase identifier")
    metadata = _safe_fields(
        fields, _CONTEXT_FIELDS | {"outcome", "error_type", "duration_ms"}
    )
    terminal = decision in {
        "job_started",
        "job_finished",
        "stage_result",
        "summary_saved",
        "summary_references_processed",
    }
    label = action_label("work", decision)
    _write_log(
        {
            "trigger": "unknown",
            **current_trigger(),
            **metadata,
            "decision": decision,
            "utc_timestamp": datetime.now(timezone.utc).isoformat(),
        },
        label.prefix,
        _work_logger,
        "work_decision",
        level=logging.DEBUG if terminal else logging.INFO,
    )


class BillableEvent:
    def __init__(
        self,
        provider: str,
        operation: str,
        fields: dict[str, Any],
        *,
        emitter: Callable | None = None,
    ) -> None:
        self.event_id = str(uuid4())
        self._started = time.monotonic()
        self._lock = Lock()
        self._finished = False
        self._emitter = emitter or _emit
        self._fields = MappingProxyType(
            {
                "trigger": "unknown",
                "billing": "potential",
                **fields,
                "event_id": self.event_id,
                "provider": provider,
                "operation": operation,
            }
        )

    @classmethod
    def start(cls, provider: str, operation: str, **fields: Any) -> BillableEvent:
        if (
            not isinstance(provider, str)
            or not provider.strip()
            or not isinstance(operation, str)
            or not operation.strip()
        ):
            raise ValueError("Billable provider and operation must be nonblank strings")
        metadata = {**current_trigger(), **_safe_fields(fields, _CONTEXT_FIELDS)}
        event = cls(provider[:128], operation[:128], metadata)
        event._start_record()
        return event

    def _start_record(self) -> None:
        self._emitter(
            {
                **self._fields,
                "phase": "START",
                "utc_timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    def finish(
        self,
        outcome: str = "success",
        *,
        error: BaseException | None = None,
        **fields: Any,
    ) -> bool:
        if outcome not in _OUTCOMES:
            raise ValueError("Unsupported billable outcome")
        terminal = _safe_fields(fields, _END_FIELDS)
        if error is not None:
            terminal["error_type"] = type(error).__name__
            status = getattr(error, "status_code", None) or getattr(
                error, "status", None
            )
            if type(status) is int and 100 <= status <= 599:
                terminal.setdefault("http_status", status)
        with self._lock:
            if self._finished:
                return False
            self._emitter(
                {
                    **self._fields,
                    **terminal,
                    "phase": "END",
                    "outcome": outcome,
                    "duration_ms": round(
                        max(0, time.monotonic() - self._started) * 1000, 3
                    ),
                    "utc_timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            self._finished = True
        return True


def error_outcome(error: BaseException) -> str:
    if isinstance(
        error,
        (
            asyncio.CancelledError,
            FutureCancelledError,
            GeneratorExit,
            KeyboardInterrupt,
        ),
    ):
        return "cancelled"
    if isinstance(error, TimeoutError) or any(
        (kind.__module__, kind.__name__) in _TIMEOUT_TYPES
        for kind in type(error).__mro__
    ):
        return "timeout"
    return "failed"


@contextmanager
def _event_scope(event: BillableEvent) -> Iterator[BillableEvent]:
    with trigger_context(parent_event_id=event.event_id):
        try:
            yield event
        except BaseException as error:
            event.finish(error_outcome(error), error=error)
            raise
        else:
            event.finish()


@contextmanager
def billable_operation(
    provider: str, operation: str, **fields: Any
) -> Iterator[BillableEvent]:
    with _event_scope(BillableEvent.start(provider, operation, **fields)) as event:
        yield event


@contextmanager
def action_operation(
    resource: str,
    action: str,
    *,
    owner: str,
    local_only: bool = False,
    invocation: ToolInvocation | None = None,
    **fields: Any,
) -> Iterator[BillableEvent]:
    if not isinstance(owner, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", owner):
        raise ValueError("Action owner must be a short lowercase identifier")
    if type(local_only) is not bool:
        raise ValueError("Local-only classification must be a boolean")
    with ExitStack() as scopes:
        fields = {
            "request_id": current_trigger().get("request_id") or str(uuid4()),
            **fields,
        }
        backend = None
        if resource_name(resource) == "MEMORY":
            from services.memory.backends import backend_snapshot

            backend = scopes.enter_context(backend_snapshot())
            fields = {
                **fields,
                "memory_backend": backend
                if backend in {"pinecone", "lancedb", "pgvector"}
                else "unknown",
            }
        scopes.enter_context(trigger_context(**fields))
        label = action_label(
            resource,
            action,
            memory_backend=backend,
            graph_type=current_trigger().get("graph"),
            local_only=local_only,
        )
        request_id = current_trigger().get("request_id")
        previous = next(
            (
                frame
                for frame in reversed(_actions.get())
                if (frame.resource, frame.action) == (label.resource, label.action)
                and frame.request_id == request_id
            ),
            None,
        )
        delegated = (
            previous is not None
            and previous.owner in _ADAPTER_OWNERS
            and previous.owner != owner
        )

        def emit(record):
            prefix, display_json = label.prefix, None
            if invocation is not None and record["phase"] == "START":
                record = {
                    **record,
                    "agent": invocation.agent,
                    "tool": invocation.tool,
                    "params": json.loads(invocation.params_json),
                }
                prefix = (
                    invocation.format_prefix("MCP")
                    if owner == "mcp"
                    else invocation.prefix
                )
                display_json = invocation.params_json
            _write_log(
                record,
                prefix,
                _action_logger,
                "operation_event",
                level=_event_level(record),
                display_json=display_json,
            )

        event = (
            previous.event
            if delegated
            else BillableEvent(
                label.resource.lower(),
                label.action.lower(),
                {
                    **current_trigger(),
                    "billing": label.billing,
                },
                emitter=emit,
            )
        )
        token = _actions.set(
            (
                *_actions.get(),
                _ActionFrame(label.resource, label.action, owner, request_id, event),
            )
        )
        scopes.callback(_actions.reset, token)
        if delegated:
            yield event
            return
        event._start_record()
        yield scopes.enter_context(_event_scope(event))


def submit_with_context(
    executor: Executor, function: Callable[..., _T], *args: Any, **kwargs: Any
) -> Future[_T]:
    context = copy_context()
    return executor.submit(context.run, partial(function, *args, **kwargs))

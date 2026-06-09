import pytest

from src.policies.audit import LoggingAuditSink, NoopAuditSink
from src.policies.base import Permission
from src.policies.scoped import PolicyContext, PolicyDecision


@pytest.mark.unit
@pytest.mark.asyncio
async def test_noop_audit_sink_records_without_side_effects():
    sink = NoopAuditSink()
    context = PolicyContext(subject="user-1", role="user")
    decision = PolicyDecision(allowed=True, permission=Permission.READ, code="ok", reason="allowed")

    assert await sink.record(decision, context) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_logging_audit_sink_emits_structured_decision(monkeypatch):
    fake_logger = FakeLogger()
    monkeypatch.setattr("src.policies.audit.get_logger", lambda name: fake_logger)
    sink = LoggingAuditSink(logger_name="test.audit")
    context = PolicyContext(
        subject="user-1",
        role="user",
        tenant_ids=frozenset({"tenant-a"}),
        resource_type="project",
        resource_id="project-1",
        resource_tenant_id="tenant-a",
        request_id="request-1",
    )
    decision = PolicyDecision(
        allowed=True,
        permission=Permission.WRITE,
        code="tenant_scope",
        reason="Subject is in resource tenant scope",
    )

    await sink.record(decision, context)

    assert fake_logger.calls == [
        (
            "authorization_decision",
            {
                "allowed": True,
                "audit_metadata": {},
                "code": "tenant_scope",
                "permission": "write",
                "reason": "Subject is in resource tenant scope",
                "request_id": "request-1",
                "resource_id": "project-1",
                "resource_owner_id": None,
                "resource_tenant_id": "tenant-a",
                "resource_type": "project",
                "role": "user",
                "subject": "user-1",
                "tenant_ids": ["tenant-a"],
            },
        )
    ]


class FakeLogger:
    def __init__(self) -> None:
        self.calls = []

    def info(self, event: str, **kwargs) -> None:
        self.calls.append((event, kwargs))

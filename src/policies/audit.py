from typing import Protocol

from src.policies.scoped import PolicyContext, PolicyDecision
from src.utils.logging import get_logger


class AuditSink(Protocol):
    async def record(self, decision: PolicyDecision, context: PolicyContext) -> None: ...


class NoopAuditSink:
    async def record(self, decision: PolicyDecision, context: PolicyContext) -> None:
        return None


class LoggingAuditSink:
    def __init__(self, *, logger_name: str = "agent_smith.audit") -> None:
        self.logger = get_logger(logger_name)

    async def record(self, decision: PolicyDecision, context: PolicyContext) -> None:
        self.logger.info(
            "authorization_decision",
            allowed=decision.allowed,
            code=decision.code,
            reason=decision.reason,
            permission=decision.permission.value,
            subject=context.subject,
            role=context.role,
            tenant_ids=sorted(context.tenant_ids),
            resource_type=context.resource_type,
            resource_id=context.resource_id,
            resource_tenant_id=context.resource_tenant_id,
            resource_owner_id=context.resource_owner_id,
            request_id=context.request_id,
            audit_metadata=dict(decision.audit_metadata),
        )

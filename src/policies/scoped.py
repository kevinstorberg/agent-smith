from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from src.policies.base import Permission, has_permission

DEFAULT_TENANT_CLAIMS = ("tenant_ids", "tenant_id")


@dataclass(frozen=True)
class PolicyContext:
    subject: str
    role: str
    tenant_ids: frozenset[str] = field(default_factory=frozenset)
    action: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    resource_tenant_id: str | None = None
    resource_owner_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    permission: Permission
    code: str
    reason: str
    audit_metadata: Mapping[str, Any] = field(default_factory=dict)


class OwnershipPolicy:
    def __init__(self, *, allow_owner: bool = False) -> None:
        self.allow_owner = allow_owner

    def owner_matches(self, context: PolicyContext) -> bool:
        return bool(self.allow_owner and context.resource_owner_id and context.resource_owner_id == context.subject)

    def tenant_matches(self, context: PolicyContext) -> bool:
        return bool(context.resource_tenant_id and context.resource_tenant_id in context.tenant_ids)

    def has_scope(self, context: PolicyContext) -> bool:
        return bool(context.resource_tenant_id or context.resource_owner_id)


def build_policy_context(
    claims: Mapping[str, Any],
    *,
    role_claim: str = "role",
    subject_claim: str = "sub",
    tenant_claims: Iterable[str] = DEFAULT_TENANT_CLAIMS,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    resource_tenant_id: str | None = None,
    resource_owner_id: str | None = None,
    request_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PolicyContext:
    subject = _required_claim(claims, subject_claim)
    role = _required_claim(claims, role_claim)
    tenant_ids = _tenant_ids_from_claims(claims, tenant_claims)

    return PolicyContext(
        subject=subject,
        role=role,
        tenant_ids=frozenset(tenant_ids),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_tenant_id=resource_tenant_id,
        resource_owner_id=resource_owner_id,
        request_id=request_id,
        metadata=metadata or {},
    )


def authorize_scope(
    context: PolicyContext,
    permission: Permission,
    *,
    allow_owner: bool = False,
    audit: Mapping[str, Any] | None = None,
) -> PolicyDecision:
    audit_metadata = _audit_metadata(context)
    if audit:
        audit_metadata.update(audit)
    if not has_permission(context.role, permission):
        return _deny(
            permission,
            code="insufficient_permission",
            reason=f"Role {context.role!r} does not have {permission.value} permission",
            audit_metadata=audit_metadata,
        )

    if has_permission(context.role, Permission.ADMIN):
        return _allow(
            permission,
            code="admin_scope",
            reason="Admin role can access scoped resources",
            audit_metadata=audit_metadata,
        )

    ownership = OwnershipPolicy(allow_owner=allow_owner)
    if context.resource_tenant_id and not ownership.tenant_matches(context):
        return _deny(
            permission,
            code="tenant_mismatch",
            reason="Resource tenant is not in subject tenant scope",
            audit_metadata=audit_metadata,
        )

    if ownership.tenant_matches(context):
        return _allow(
            permission, code="tenant_scope", reason="Subject is in resource tenant scope", audit_metadata=audit_metadata
        )

    if ownership.owner_matches(context):
        return _allow(permission, code="owner_scope", reason="Subject owns the resource", audit_metadata=audit_metadata)

    if not ownership.has_scope(context):
        return _deny(
            permission,
            code="missing_resource_scope",
            reason="Scoped authorization requires resource tenant or owner context",
            audit_metadata=audit_metadata,
        )

    return _deny(
        permission,
        code="scope_denied",
        reason="Subject is not authorized for the resource scope",
        audit_metadata=audit_metadata,
    )


def _required_claim(claims: Mapping[str, Any], name: str) -> str:
    value = claims.get(name)
    if value in (None, ""):
        raise ValueError(f"Missing required claim: {name}")
    return str(value)


def _tenant_ids_from_claims(claims: Mapping[str, Any], names: Iterable[str]) -> set[str]:
    tenant_ids: set[str] = set()
    for name in names:
        value = claims.get(name)
        if value in (None, ""):
            continue
        if isinstance(value, str):
            tenant_ids.add(value)
        elif isinstance(value, Iterable):
            tenant_ids.update(str(item) for item in value if item not in (None, ""))
        else:
            tenant_ids.add(str(value))
    return tenant_ids


def _allow(permission: Permission, *, code: str, reason: str, audit_metadata: Mapping[str, Any]) -> PolicyDecision:
    return PolicyDecision(allowed=True, permission=permission, code=code, reason=reason, audit_metadata=audit_metadata)


def _deny(permission: Permission, *, code: str, reason: str, audit_metadata: Mapping[str, Any]) -> PolicyDecision:
    return PolicyDecision(allowed=False, permission=permission, code=code, reason=reason, audit_metadata=audit_metadata)


def _audit_metadata(context: PolicyContext) -> dict[str, Any]:
    return {
        "subject": context.subject,
        "role": context.role,
        "tenant_ids": sorted(context.tenant_ids),
        "action": context.action,
        "resource_type": context.resource_type,
        "resource_id": context.resource_id,
        "resource_tenant_id": context.resource_tenant_id,
        "resource_owner_id": context.resource_owner_id,
        "request_id": context.request_id,
        **dict(context.metadata),
    }

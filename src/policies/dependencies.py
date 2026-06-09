import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import Depends, HTTPException, Request

from src.api.errors import request_id_from_request
from src.policies.audit import AuditSink, NoopAuditSink
from src.policies.base import Permission, has_permission
from src.policies.scoped import DEFAULT_TENANT_CLAIMS, PolicyContext, authorize_scope, build_policy_context
from src.security.auth import require_auth

ResourceScope = (
    Mapping[str, Any] | Callable[[Request, Mapping[str, Any]], Mapping[str, Any] | Awaitable[Mapping[str, Any]]]
)


def require_permission(permission: Permission, *, role_claim: str = "role") -> Callable:
    async def _check(claims: dict = Depends(require_auth)) -> dict:
        role = claims.get(role_claim)
        if role is None:
            raise HTTPException(status_code=403, detail=f"Missing role claim: {role_claim}")
        if not has_permission(role, permission):
            raise HTTPException(status_code=403, detail=f"Insufficient permissions: requires {permission.value}")
        return claims

    return _check


def require_state_permission(permission: Permission) -> Callable:
    async def _check(request: Request) -> str:
        role = getattr(request.state, "role", None)
        if role is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if not has_permission(role, permission):
            raise HTTPException(status_code=403, detail=f"Insufficient permissions: requires {permission.value}")
        return role

    return _check


def require_scoped_permission(
    permission: Permission,
    *,
    resource_scope: ResourceScope | None = None,
    allow_owner: bool = False,
    audit_sink: AuditSink | None = None,
    fail_on_audit_error: bool = True,
    role_claim: str = "role",
    subject_claim: str = "sub",
    tenant_claims: tuple[str, ...] = DEFAULT_TENANT_CLAIMS,
) -> Callable:
    async def _check(request: Request, claims: dict = Depends(require_auth)) -> PolicyContext:
        scope_values = await _resolve_resource_scope(resource_scope, request, claims)
        try:
            context = build_policy_context(
                claims,
                role_claim=role_claim,
                subject_claim=subject_claim,
                tenant_claims=tenant_claims,
                action=str(scope_values.get("action") or permission.value),
                resource_type=_optional_str(scope_values.get("resource_type")),
                resource_id=_optional_str(scope_values.get("resource_id")),
                resource_tenant_id=_optional_str(scope_values.get("resource_tenant_id")),
                resource_owner_id=_optional_str(scope_values.get("resource_owner_id")),
                request_id=request_id_from_request(request),
                metadata=_metadata(scope_values.get("metadata")),
            )
        except ValueError as e:
            raise HTTPException(status_code=403, detail=str(e))

        decision = authorize_scope(
            context,
            permission,
            allow_owner=allow_owner,
            audit=_metadata(scope_values.get("audit")),
        )
        await _record_audit_decision(
            audit_sink or NoopAuditSink(),
            decision=decision,
            context=context,
            fail_on_audit_error=fail_on_audit_error,
        )

        if not decision.allowed:
            raise HTTPException(status_code=403, detail=decision.reason)
        return context

    return _check


async def _resolve_resource_scope(
    resource_scope: ResourceScope | None,
    request: Request,
    claims: Mapping[str, Any],
) -> Mapping[str, Any]:
    if resource_scope is None:
        return {}
    if isinstance(resource_scope, Mapping):
        return resource_scope

    result = resource_scope(request, claims)
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, Mapping):
        raise HTTPException(status_code=500, detail="Resource scope loader must return a mapping")
    return result


async def _record_audit_decision(
    audit_sink: AuditSink,
    *,
    decision,
    context: PolicyContext,
    fail_on_audit_error: bool,
) -> None:
    try:
        await audit_sink.record(decision, context)
    except Exception:
        if fail_on_audit_error:
            raise HTTPException(status_code=500, detail="Protected action audit failed")


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _metadata(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise HTTPException(status_code=500, detail="Policy metadata must be a mapping")
    return value

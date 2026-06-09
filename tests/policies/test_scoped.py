import pytest

from src.policies.base import Permission
from src.policies.scoped import PolicyContext, authorize_scope, build_policy_context


@pytest.mark.unit
def test_build_policy_context_from_claims():
    context = build_policy_context(
        {"sub": "user-1", "role": "user", "tenant_ids": ["tenant-a", "tenant-b"]},
        resource_type="project",
        resource_id="project-1",
        resource_tenant_id="tenant-a",
        resource_owner_id="user-2",
        request_id="request-1",
        metadata={"source": "test"},
    )

    assert context.subject == "user-1"
    assert context.role == "user"
    assert context.tenant_ids == frozenset({"tenant-a", "tenant-b"})
    assert context.resource_type == "project"
    assert context.resource_id == "project-1"
    assert context.resource_tenant_id == "tenant-a"
    assert context.resource_owner_id == "user-2"
    assert context.request_id == "request-1"
    assert context.metadata == {"source": "test"}


@pytest.mark.unit
def test_build_policy_context_accepts_single_tenant_claim():
    context = build_policy_context({"sub": "user-1", "role": "user", "tenant_id": "tenant-a"})

    assert context.tenant_ids == frozenset({"tenant-a"})


@pytest.mark.unit
def test_build_policy_context_requires_subject_and_role():
    with pytest.raises(ValueError, match="Missing required claim: sub"):
        build_policy_context({"role": "user"})

    with pytest.raises(ValueError, match="Missing required claim: role"):
        build_policy_context({"sub": "user-1"})


@pytest.mark.unit
def test_admin_can_access_cross_tenant_resource():
    context = PolicyContext(
        subject="admin-1",
        role="admin",
        tenant_ids=frozenset({"tenant-a"}),
        resource_tenant_id="tenant-b",
    )

    decision = authorize_scope(context, Permission.DELETE)

    assert decision.allowed is True
    assert decision.code == "admin_scope"


@pytest.mark.unit
def test_user_can_access_same_tenant_resource_with_permission():
    context = PolicyContext(
        subject="user-1",
        role="user",
        tenant_ids=frozenset({"tenant-a"}),
        resource_tenant_id="tenant-a",
    )

    decision = authorize_scope(context, Permission.WRITE)

    assert decision.allowed is True
    assert decision.code == "tenant_scope"


@pytest.mark.unit
def test_tenant_mismatch_denies_non_admin():
    context = PolicyContext(
        subject="user-1",
        role="user",
        tenant_ids=frozenset({"tenant-a"}),
        resource_tenant_id="tenant-b",
        resource_owner_id="user-1",
    )

    decision = authorize_scope(context, Permission.READ, allow_owner=True)

    assert decision.allowed is False
    assert decision.code == "tenant_mismatch"


@pytest.mark.unit
def test_owner_access_is_opt_in():
    context = PolicyContext(
        subject="user-1",
        role="user",
        resource_owner_id="user-1",
    )

    denied = authorize_scope(context, Permission.READ)
    allowed = authorize_scope(context, Permission.READ, allow_owner=True)

    assert denied.allowed is False
    assert denied.code == "scope_denied"
    assert allowed.allowed is True
    assert allowed.code == "owner_scope"


@pytest.mark.unit
def test_missing_scope_fails_closed():
    context = PolicyContext(subject="user-1", role="user")

    decision = authorize_scope(context, Permission.READ)

    assert decision.allowed is False
    assert decision.code == "missing_resource_scope"


@pytest.mark.unit
def test_missing_role_permission_denies_before_scope():
    context = PolicyContext(
        subject="user-1",
        role="readonly",
        tenant_ids=frozenset({"tenant-a"}),
        resource_tenant_id="tenant-a",
    )

    decision = authorize_scope(context, Permission.WRITE)

    assert decision.allowed is False
    assert decision.code == "insufficient_permission"


@pytest.mark.unit
def test_authorize_scope_merges_extra_audit_metadata():
    context = PolicyContext(
        subject="user-1",
        role="user",
        tenant_ids=frozenset({"tenant-a"}),
        resource_tenant_id="tenant-a",
        request_id="request-1",
    )

    decision = authorize_scope(context, Permission.READ, audit={"route": "/projects/1"})

    assert decision.audit_metadata["request_id"] == "request-1"
    assert decision.audit_metadata["route"] == "/projects/1"

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from src.policies.base import Permission, has_permission
from src.policies.dependencies import require_permission, require_scoped_permission, require_state_permission
from src.policies.roles import ROLE_PERMISSIONS, Role
from src.policies.scoped import PolicyContext
from src.security.auth import create_token


@pytest.mark.unit
class TestRolePermissions:
    def test_admin_has_all_permissions(self):
        for perm in Permission:
            assert has_permission(Role.ADMIN, perm)

    def test_readonly_only_has_read(self):
        assert has_permission(Role.READONLY, Permission.READ)
        assert not has_permission(Role.READONLY, Permission.WRITE)
        assert not has_permission(Role.READONLY, Permission.DELETE)
        assert not has_permission(Role.READONLY, Permission.ADMIN)

    def test_user_has_read_write_no_admin(self):
        assert has_permission(Role.USER, Permission.READ)
        assert has_permission(Role.USER, Permission.WRITE)
        assert not has_permission(Role.USER, Permission.ADMIN)
        assert not has_permission(Role.USER, Permission.DELETE)

    def test_service_has_read_write(self):
        assert has_permission(Role.SERVICE, Permission.READ)
        assert has_permission(Role.SERVICE, Permission.WRITE)
        assert not has_permission(Role.SERVICE, Permission.ADMIN)

    def test_unknown_role_has_no_permissions(self):
        assert not has_permission("unknown", Permission.READ)
        assert not has_permission("unknown", Permission.WRITE)


@pytest.mark.unit
class TestRolePermissionMapping:
    def test_all_roles_have_mapping(self):
        for role in Role:
            assert role in ROLE_PERMISSIONS

    def test_admin_superset_of_user(self):
        admin_perms = ROLE_PERMISSIONS[Role.ADMIN]
        user_perms = ROLE_PERMISSIONS[Role.USER]
        assert user_perms.issubset(admin_perms)


@pytest.mark.unit
class TestRequirePermission:
    def test_returns_dependency_callable(self):
        dep = require_permission(Permission.READ)
        assert callable(dep)

    def test_admin_token_passes_permission_check(self):
        app = _create_policy_test_app()
        token = create_token("user-1", extra_claims={"role": "admin"})
        client = TestClient(app)

        response = client.get("/admin", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        assert response.json() == {"sub": "user-1", "role": "admin"}

    def test_insufficient_jwt_role_returns_403(self):
        app = _create_policy_test_app()
        token = create_token("user-1", extra_claims={"role": "user"})
        client = TestClient(app)

        response = client.get("/admin", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 403
        assert response.json()["detail"] == "Insufficient permissions: requires admin"

    def test_missing_jwt_returns_401(self):
        app = _create_policy_test_app()
        client = TestClient(app)

        response = client.get("/admin")

        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"

    def test_invalid_jwt_returns_401(self):
        app = _create_policy_test_app()
        client = TestClient(app)

        response = client.get("/admin", headers={"Authorization": "Bearer invalid.token.value"})

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid token"

    def test_missing_role_claim_returns_403(self):
        app = _create_policy_test_app()
        token = create_token("user-1")
        client = TestClient(app)

        response = client.get("/admin", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 403
        assert response.json()["detail"] == "Missing role claim: role"

    def test_custom_role_claim_passes(self):
        app = _create_policy_test_app()
        token = create_token("service-1", extra_claims={"app_role": "service"})
        client = TestClient(app)

        response = client.get("/custom-role", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        assert response.json() == {"sub": "service-1", "role": "service"}

    def test_state_permission_still_supports_request_state_role(self):
        app = _create_policy_test_app()
        client = TestClient(app)

        response = client.get("/state-read", headers={"X-Role": "readonly"})

        assert response.status_code == 200
        assert response.json() == {"role": "readonly"}

    def test_state_permission_missing_role_returns_401(self):
        app = _create_policy_test_app()
        client = TestClient(app)

        response = client.get("/state-read")

        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"

    def test_state_permission_insufficient_role_returns_403(self):
        app = _create_policy_test_app()
        client = TestClient(app)

        response = client.get("/state-delete", headers={"X-Role": "readonly"})

        assert response.status_code == 403
        assert response.json()["detail"] == "Insufficient permissions: requires delete"


@pytest.mark.unit
class TestRequireScopedPermission:
    def test_same_tenant_resource_passes_and_records_audit(self):
        audit_sink = RecordingAuditSink()
        app = _create_scoped_policy_test_app(audit_sink)
        token = create_token("user-1", extra_claims={"role": "user", "tenant_ids": ["tenant-a"]})
        client = TestClient(app)

        response = client.get(
            "/tenant-resource",
            headers={"Authorization": f"Bearer {token}", "X-Request-ID": "request-1"},
        )

        assert response.status_code == 200
        assert response.json() == {"subject": "user-1", "tenant_ids": ["tenant-a"], "request_id": "request-1"}
        assert len(audit_sink.records) == 1
        decision, context = audit_sink.records[0]
        assert decision.allowed is True
        assert decision.code == "tenant_scope"
        assert context.request_id == "request-1"

    def test_tenant_mismatch_denies_and_records_audit(self):
        audit_sink = RecordingAuditSink()
        app = _create_scoped_policy_test_app(audit_sink)
        token = create_token("user-1", extra_claims={"role": "user", "tenant_ids": ["tenant-a"]})
        client = TestClient(app)

        response = client.get("/other-tenant-resource", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 403
        assert response.json()["detail"] == "Resource tenant is not in subject tenant scope"
        assert len(audit_sink.records) == 1
        assert audit_sink.records[0][0].allowed is False
        assert audit_sink.records[0][0].code == "tenant_mismatch"

    def test_admin_can_access_cross_tenant_resource(self):
        app = _create_scoped_policy_test_app(RecordingAuditSink())
        token = create_token("admin-1", extra_claims={"role": "admin", "tenant_ids": ["tenant-a"]})
        client = TestClient(app)

        response = client.get("/other-tenant-resource", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        assert response.json()["subject"] == "admin-1"

    def test_owner_access_is_opt_in_for_dependency(self):
        app = _create_scoped_policy_test_app(RecordingAuditSink())
        token = create_token("user-1", extra_claims={"role": "user"})
        client = TestClient(app)

        denied = client.get("/owned-resource-denied", headers={"Authorization": f"Bearer {token}"})
        allowed = client.get("/owned-resource-allowed", headers={"Authorization": f"Bearer {token}"})

        assert denied.status_code == 403
        assert denied.json()["detail"] == "Subject is not authorized for the resource scope"
        assert allowed.status_code == 200
        assert allowed.json()["subject"] == "user-1"

    def test_missing_scope_fails_closed(self):
        app = _create_scoped_policy_test_app(RecordingAuditSink())
        token = create_token("user-1", extra_claims={"role": "user"})
        client = TestClient(app)

        response = client.get("/missing-scope", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 403
        assert response.json()["detail"] == "Scoped authorization requires resource tenant or owner context"

    def test_resource_scope_loader_can_use_request_and_claims(self):
        app = _create_scoped_policy_test_app(RecordingAuditSink())
        token = create_token("user-1", extra_claims={"role": "user", "tenant_id": "tenant-a"})
        client = TestClient(app)

        response = client.get("/projects/project-1", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        assert response.json()["resource_id"] == "project-1"

    def test_audit_failure_fails_closed(self):
        app = _create_scoped_policy_test_app(FailingAuditSink())
        token = create_token("user-1", extra_claims={"role": "user", "tenant_ids": ["tenant-a"]})
        client = TestClient(app)

        response = client.get("/tenant-resource", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 500
        assert response.json()["detail"] == "Protected action audit failed"


def _create_policy_test_app() -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def role_middleware(request: Request, call_next):
        role = request.headers.get("X-Role")
        if role:
            request.state.role = role
        return await call_next(request)

    @app.get("/admin")
    async def admin_route(claims: dict = Depends(require_permission(Permission.ADMIN))):
        return {"sub": claims["sub"], "role": claims["role"]}

    @app.get("/custom-role")
    async def custom_role_route(claims: dict = Depends(require_permission(Permission.WRITE, role_claim="app_role"))):
        return {"sub": claims["sub"], "role": claims["app_role"]}

    @app.get("/state-read")
    async def state_read_route(role: str = Depends(require_state_permission(Permission.READ))):
        return {"role": role}

    @app.get("/state-delete")
    async def state_delete_route(role: str = Depends(require_state_permission(Permission.DELETE))):
        return {"role": role}

    return app


class RecordingAuditSink:
    def __init__(self) -> None:
        self.records = []

    async def record(self, decision, context) -> None:
        self.records.append((decision, context))


class FailingAuditSink:
    async def record(self, decision, context) -> None:
        raise RuntimeError("audit unavailable")


def _create_scoped_policy_test_app(audit_sink) -> FastAPI:
    app = FastAPI()

    @app.get("/tenant-resource")
    async def tenant_resource(
        context: PolicyContext = Depends(
            require_scoped_permission(
                Permission.WRITE,
                resource_scope={
                    "resource_type": "project",
                    "resource_id": "project-1",
                    "resource_tenant_id": "tenant-a",
                },
                audit_sink=audit_sink,
            )
        ),
    ):
        return {
            "subject": context.subject,
            "tenant_ids": sorted(context.tenant_ids),
            "request_id": context.request_id,
        }

    @app.get("/other-tenant-resource")
    async def other_tenant_resource(
        context: PolicyContext = Depends(
            require_scoped_permission(
                Permission.WRITE,
                resource_scope={
                    "resource_type": "project",
                    "resource_id": "project-2",
                    "resource_tenant_id": "tenant-b",
                },
                audit_sink=audit_sink,
            )
        ),
    ):
        return {"subject": context.subject}

    @app.get("/owned-resource-denied")
    async def owned_resource_denied(
        context: PolicyContext = Depends(
            require_scoped_permission(
                Permission.READ,
                resource_scope={"resource_type": "project", "resource_id": "project-3", "resource_owner_id": "user-1"},
                audit_sink=audit_sink,
            )
        ),
    ):
        return {"subject": context.subject}

    @app.get("/owned-resource-allowed")
    async def owned_resource_allowed(
        context: PolicyContext = Depends(
            require_scoped_permission(
                Permission.READ,
                resource_scope={"resource_type": "project", "resource_id": "project-3", "resource_owner_id": "user-1"},
                allow_owner=True,
                audit_sink=audit_sink,
            )
        ),
    ):
        return {"subject": context.subject}

    @app.get("/missing-scope")
    async def missing_scope(
        context: PolicyContext = Depends(
            require_scoped_permission(
                Permission.READ,
                resource_scope={"resource_type": "project", "resource_id": "project-4"},
                audit_sink=audit_sink,
            )
        ),
    ):
        return {"subject": context.subject}

    async def project_scope(request: Request, claims: dict):
        return {
            "resource_type": "project",
            "resource_id": request.path_params["project_id"],
            "resource_tenant_id": claims["tenant_id"],
        }

    @app.get("/projects/{project_id}")
    async def project_route(
        context: PolicyContext = Depends(
            require_scoped_permission(Permission.READ, resource_scope=project_scope, audit_sink=audit_sink)
        ),
    ):
        return {"resource_id": context.resource_id}

    return app

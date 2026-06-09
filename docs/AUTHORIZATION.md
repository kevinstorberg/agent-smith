# Authorization

Cairn separates role permissions from resource scope:

- RBAC answers whether a role has a permission.
- Scoped authorization answers whether a subject can use that permission on a
  specific resource.

The source of truth lives in `src/policies/`:

- `base.py` and `roles.py` define roles and permissions.
- `scoped.py` defines policy context, decisions, and ownership checks.
- `dependencies.py` adapts those rules to FastAPI dependencies.
- `audit.py` defines protocol-only audit sinks.

## Scoped Policy Flow

Routers should collect transport identifiers and call services to load resource
scope. Services own domain-specific resource loading. Policies evaluate the
subject, role, tenant scope, owner scope, and requested permission.

Use `require_scoped_permission()` when a route needs tenant or owner checks. The
dependency accepts either a static scope mapping or a resource scope loader that
receives the request and verified JWT claims.

```python
from fastapi import Depends

from src.policies.base import Permission
from src.policies.dependencies import require_scoped_permission
from src.policies.scoped import PolicyContext


async def project_scope(request, claims):
    project = await load_project(request.path_params["project_id"])
    return {
        "resource_type": "project",
        "resource_id": str(project.id),
        "resource_tenant_id": str(project.tenant_id),
        "resource_owner_id": str(project.owner_id),
    }


async def read_project(
    context: PolicyContext = Depends(
        require_scoped_permission(
            Permission.READ,
            resource_scope=project_scope,
            allow_owner=True,
        )
    ),
):
    ...
```

## Audit Hooks

Audit persistence is intentionally not chosen by the template. The default sink
is no-op; `LoggingAuditSink` emits structured authorization decisions; downstream
apps can implement `AuditSink` for a database, queue, or vendor system.

Protected actions fail closed when audit recording raises unless a route
explicitly opts out through the dependency configuration.

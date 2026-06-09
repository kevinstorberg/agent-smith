from enum import Enum


class Permission(str, Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    ADMIN = "admin"


def has_permission(role: str, permission: Permission) -> bool:
    from src.policies.roles import ROLE_PERMISSIONS, Role

    try:
        resolved_role = Role(role)
    except ValueError:
        return False
    return permission in ROLE_PERMISSIONS.get(resolved_role, set())

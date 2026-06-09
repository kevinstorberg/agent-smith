from enum import Enum

from src.policies.base import Permission


class Role(str, Enum):
    ADMIN = "admin"
    USER = "user"
    SERVICE = "service"
    READONLY = "readonly"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: {Permission.READ, Permission.WRITE, Permission.DELETE, Permission.ADMIN},
    Role.USER: {Permission.READ, Permission.WRITE},
    Role.SERVICE: {Permission.READ, Permission.WRITE},
    Role.READONLY: {Permission.READ},
}

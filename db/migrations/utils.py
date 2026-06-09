import importlib
import pkgutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op
from sqlalchemy.dialects import postgresql


def import_model_modules(models_dir: Path, *, package_name: str = "db.models") -> None:
    for _, module_name, _ in pkgutil.iter_modules([str(models_dir)]):
        if not module_name.startswith("_"):
            importlib.import_module(f"{package_name}.{module_name}")


def sync_database_url(database_url: str) -> str:
    return database_url.replace("+asyncpg", "")


def postgres_enum(name: str, values: Sequence[str]) -> postgresql.ENUM:
    if not name:
        raise ValueError("PostgreSQL enum name is required")
    if not values:
        raise ValueError(f"PostgreSQL enum {name!r} requires at least one value")
    return postgresql.ENUM(*values, name=name, create_type=False)


def create_postgres_enum(enum_type: postgresql.ENUM, bind: Any | None = None) -> None:
    enum_type.create(bind or op.get_bind(), checkfirst=True)


def drop_postgres_enum(enum_type: postgresql.ENUM, bind: Any | None = None) -> None:
    enum_type.drop(bind or op.get_bind(), checkfirst=True)

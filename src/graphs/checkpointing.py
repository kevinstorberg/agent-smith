from functools import lru_cache
from typing import Any

from config.models import GraphConfig
from db.migrations.utils import sync_database_url
from src.settings import get_settings


def create_checkpointer(config: GraphConfig, *, database_url: str | None = None) -> Any | None:
    backend = config.checkpoint.backend.lower()

    if backend == "none":
        return None

    if backend == "memory":
        return _create_memory_saver()

    if backend == "postgres":
        resolved_database_url = sync_database_url(database_url or get_settings().database_url)
        return _create_postgres_saver(resolved_database_url)

    raise ValueError(f"Unknown graph checkpoint backend: {config.checkpoint.backend!r}")


def reset_checkpointers() -> None:
    _create_memory_saver.cache_clear()
    _create_postgres_saver.cache_clear()


@lru_cache(maxsize=1)
def _create_memory_saver() -> Any:
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


@lru_cache(maxsize=8)
def _create_postgres_saver(resolved_database_url: str) -> Any:
    saver_cls, psycopg = _load_postgres_dependencies()
    connection = psycopg.connect(resolved_database_url, autocommit=True)
    saver = saver_cls(connection)
    saver.setup()
    return saver


def _load_postgres_dependencies():
    try:
        import psycopg
        from langgraph.checkpoint.postgres import PostgresSaver
    except ImportError as exc:
        raise RuntimeError(
            "Graph checkpoint backend 'postgres' requires langgraph-checkpoint-postgres. "
            "Install with `poetry install --with graph-postgres`."
        ) from exc

    return PostgresSaver, psycopg

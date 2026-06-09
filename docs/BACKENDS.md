# Backend Guide

Cairn has three backend families:

| Family | Protocol | Config key | Runtime factory | Explicit factory |
| --- | --- | --- | --- | --- |
| Memory | `memory.base.MemoryBackend` | `memory.backend` | `memory.backends.get_backend()` | `memory.backends.create_memory_backend(config)` |
| Cache | `cache.base.CacheBackend` | `cache.backend` | `cache.backends.get_cache_backend()` | `cache.backends.create_cache_backend(config)` |
| Storage | `assets.base.StorageBackend` | `storage.backend` | `assets.backends.get_storage_backend()` | `assets.backends.create_storage_backend(config)` |

The valid config shape lives in [config/models.py](../config/models.py), and the
default selected backends live in [config/default.yaml](../config/default.yaml).
Those files are the source of truth for option names.

## App Startup

Use config-driven factories when the application should follow YAML:

```python
from cache.backends import get_cache_backend
from memory.backends import get_backend
from assets.backends import get_storage_backend

memory = get_backend()
cache = get_cache_backend()
storage = get_storage_backend()
```

`get_backend()` and `get_cache_backend()` are singleton-backed because they hold
runtime state. Storage is constructed from config each time so apps can choose
their own lifecycle.

## Explicit Wiring

Use explicit factories in tests, scripts, or custom app factories where global
YAML should not be consulted:

```python
from assets.backends import create_storage_backend
from config.models import StorageConfig

storage = create_storage_backend(
    StorageConfig(backend="local", local_path="./storage")
)
```

The same pattern exists for `CacheConfig` and `MemoryConfig`.

## Switching Backends

1. Change backend selection in `config/default.yaml`.
2. Install the optional dependency if the backend needs one.
3. Set any required secret or connection env vars in `.env.{APP_ENV}` or the real
   environment.
4. Restart the app so singleton-backed factories rebuild from config.
5. Run a small smoke test for the affected behavior.

Optional dependency groups are defined in [pyproject.toml](../pyproject.toml).
Use the group names there instead of copying package lists into docs.

## Backend Notes

- In-memory memory and cache backends are local-process state. They are good for
  development and tests, not multi-process persistence.
- Redis cache is backed by `REDIS_URL` and does not require data migration
  because cache data is temporary. The local Compose host port is `REDIS_PORT`;
  app containers use the Redis service URL on the Docker network.
- pgvector memory uses the app database connection and creates its configured
  memory table on first use. Local Compose defaults to a pgvector-enabled
  Postgres image through `POSTGRES_IMAGE`.
- Pinecone memory requires `PINECONE_API_KEY` and `PINECONE_INDEX_NAME`.
- Local storage is only safe for single-node deployments. Use an object store for
  multi-node or durable file storage.
- S3 storage requires `S3_BUCKET` and the optional `aws` dependency group.
- DocumentDB utilities use the optional `documentdb` dependency group and
  `DOCUMENTDB_URI`; inject a client in tests or scripts when you do not want a
  live provider connection.

## Testing

Prefer explicit factories for unit tests and reset singleton-backed factories
between tests that depend on empty state:

```python
from cache.backends import reset_cache_backend
from memory.backends import reset_backend

reset_backend()
reset_cache_backend()
```

Integration tests that deliberately exercise provider backends should set config
and credentials at the test boundary, then reset settings and backend singletons
during teardown.

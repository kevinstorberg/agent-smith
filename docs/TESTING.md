# Testing Guide

The test suite should prove application behavior without duplicating production
setup logic. Use the fixtures and factories already provided by the template.

## Commands

Run tests through [Makefile](../Makefile). Marker definitions and pytest defaults
live in [pyproject.toml](../pyproject.toml).

```bash
make test
make test-unit
make test-integration
make test-e2e
make test-cov
make check
```

Makefile test targets set `APP_ENV=test` by default. Keep `.env.development`
focused on local runtime values; it should not affect deterministic test runs.

## Fixtures

The fixture source of truth is [tests/conftest.py](../tests/conftest.py). Use it
directly instead of recreating app, database, and HTTP client setup in each test
module.

Common fixtures:

| Fixture | Use |
| --- | --- |
| `app` | FastAPI app without database dependency overrides |
| `test_engine` | Async SQLAlchemy engine using the configured test database |
| `test_session` | Direct async database access |
| `app_with_test_db` | App with `get_session()` overridden for tests |
| `client` | Async HTTP client against `app_with_test_db` |
| `clean_db` | Truncate tables before and after a test |

Minimal endpoint test:

```python
import pytest


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")

    assert response.status_code == 200
```

## Test Boundaries

- Unit tests should construct concrete services or explicit backend factories
  directly.
- API tests should go through the `client` fixture so dependency overrides are
  exercised.
- Database integration tests should use `test_session` and `clean_db`.
- Provider tests should be marked as integration or e2e and should fail fast when
  required credentials are absent.
- Eval tests should stay explicit about provider credentials and cost.

## State Cleanup

Cairn intentionally has a few cached runtime objects. Reset them in tests that
change environment variables or depend on empty backend state:

```python
from cache.backends import reset_cache_backend
from memory.backends import reset_backend
from src.graphs.checkpointing import reset_checkpointers
from src.settings import reset_settings

reset_settings()
reset_backend()
reset_cache_backend()
reset_checkpointers()
```

Prefer explicit factories when global config is irrelevant:

```python
from cache.backends import create_cache_backend
from config.models import CacheConfig

cache = create_cache_backend(CacheConfig(backend="memory"))
```

## Mocking External Work

Patch at the boundary your code owns. For example, patch an embeddings service or
LLM builder in the module under test rather than patching provider libraries
throughout the suite.

```python
class FakeEmbeddings:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 384 for _ in texts]
```

This keeps tests fast and prevents provider APIs from becoming part of unrelated
test contracts.

## Common Failure Modes

- Stale settings after environment changes: call `reset_settings()`.
- Shared memory/cache state between tests: reset backend singletons.
- Async event loop errors: use async tests and async tools instead of
  `asyncio.run()` inside a running app.
- Database connection conflicts: test DB URLs are resolved through
  `Settings.database_url_for("test")`, so fix the settings rather than hard-coding
  URLs in tests.

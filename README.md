<img src="assets/static/logo.svg" alt="Cairn" width="120" align="left" style="margin-right: 20px; margin-bottom: 10px;"/>

# Cairn

FastAPI template for agentic Python applications with LangGraph, async SQLAlchemy,
vector memory, caching, tools, jobs, WebSockets, eval helpers, and local Docker
development.

This repository is a starting point. Clone it, keep the conventions that help,
and replace the application-specific parts with your own domain.

<br clear="left"/>

## Quick Start

```bash
poetry install
cp .env.default .env.development
docker compose up -d db redis
poetry run alembic upgrade head
poetry run uvicorn src.app:app --reload
```

If local ports are busy:

```bash
POSTGRES_PORT=55432 REDIS_PORT=56379 docker compose up -d db redis
APP_PORT=18011 docker compose up app
```

## Source Of Truth

Avoid duplicating these values in docs or app code:

| Concern | Authoritative location |
| --- | --- |
| Runtime environment and secrets | [.env.default](.env.default), [src/settings.py](src/settings.py) |
| Structural YAML config | [config/default.yaml](config/default.yaml), [config/models.py](config/models.py) |
| Graph-specific config | `config/graphs/*.yaml`, [config/loader.py](config/loader.py) |
| Database sessions and engines | [db/connection.py](db/connection.py) |
| Database model base classes | [db/base.py](db/base.py) |
| Repositories, services, and unit of work | [db/repository.py](db/repository.py), [db/unit_of_work.py](db/unit_of_work.py), [docs/REPOSITORIES_SERVICES.md](docs/REPOSITORIES_SERVICES.md) |
| Backend protocols and factories | `memory/`, `cache/`, `assets/` |
| HTTP routes | [src/routers/](src/routers) |
| Graph runtime and endpoints | [src/graphs/base.py](src/graphs/base.py), [src/graphs/endpoints.py](src/graphs/endpoints.py), [docs/GRAPHS.md](docs/GRAPHS.md) |
| Job runtime and scheduling | [src/jobs/](src/jobs), [docs/JOBS.md](docs/JOBS.md) |
| Admin/debug diagnostics | [src/diagnostics/](src/diagnostics), [scripts/inspect.py](scripts/inspect.py), [docs/ADMIN_DEBUG.md](docs/ADMIN_DEBUG.md) |
| Resource generation | [lib/cairn/generator/](lib/cairn/generator), [scripts/generate.py](scripts/generate.py), [src/routers/registry.py](src/routers/registry.py), [docs/GENERATOR.md](docs/GENERATOR.md) |
| Optional frontend | [frontend/package.json](frontend/package.json), [frontend/src/shared/config/](frontend/src/shared/config/), [frontend/src/shared/api/](frontend/src/shared/api/), [src/frontend/static.py](src/frontend/static.py), [docs/FRONTEND.md](docs/FRONTEND.md) |
| Agent Smith port and cutover | [src/agent_smith/](src/agent_smith), [scripts/agent_smith_preflight.py](scripts/agent_smith_preflight.py), [docs/AGENT_SMITH_CUTOVER.md](docs/AGENT_SMITH_CUTOVER.md) |
| JWT auth | [src/security/auth.py](src/security/auth.py) |
| Production security middleware | [src/security/middleware.py](src/security/middleware.py), [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| Authorization policies | [src/policies/](src/policies), [docs/AUTHORIZATION.md](docs/AUTHORIZATION.md) |
| FastAPI policy dependencies | [src/policies/dependencies.py](src/policies/dependencies.py) |
| API error envelope and request IDs | [src/api/errors.py](src/api/errors.py), [docs/API_ERRORS.md](docs/API_ERRORS.md) |
| Test commands and markers | [Makefile](Makefile), [pyproject.toml](pyproject.toml) |
| Bootstrap checks | [scripts/doctor.py](scripts/doctor.py), [Makefile](Makefile) |
| Security automation | [Makefile](Makefile), [.github/dependabot.yml](.github/dependabot.yml), [.github/workflows/security.yml](.github/workflows/security.yml) |

## Commands

```bash
make test
make test-unit
make test-e2e
make test-cov
make lint
make format
make format-check
make lock-check
make audit
make pre-commit
make security
make doctor
make frontend-check
make check
```

The Makefile is the command reference. Keep new quality gates there instead of
adding parallel command lists elsewhere.

Test targets run with `APP_ENV=test` by default so local `.env.development`
settings do not affect deterministic checks.

## Conventions

- Put application models under `db/models/`, schemas under `src/models/`, and
  route handlers under `src/routers/`.
- Keep routers thin. Route handlers should validate transport concerns and call
  services, repositories, tools, or graph builders for real work.
- Prefer `get_unit_of_work()` for write workflows and services. Use
  `get_session()` only when a route intentionally owns raw session access.
- Use backend protocols plus factories instead of importing concrete backends
  throughout application code.
- Put public tools in `src/tools/`. Every public module in that package is
  production auto-discovered, so keep examples in docs or tests.
- Use `require_permission()` from `src.policies.dependencies` for FastAPI routes.
  Keep pure authorization rules in `src.policies`.
- Use `build_graph_from_config()` or the built-in graph endpoints for
  config-driven ReAct graphs. Use `build_config_summary_graph()` for
  credential-free config smoke checks.
- Register app background jobs with `@register_job()` and keep job work inside
  services called through `JobContext`.
- Register generated or app-owned routers with `register_router()` when you want
  startup discovery without editing `src/app.py`.
- Keep optional frontend screens under `frontend/src/features/` and share
  backend calls through the frontend API client.

## Configuration

Runtime and secret values come from `.env.default`, `.env.{APP_ENV}`, and real
environment variables. Structural settings such as backend selection and model
defaults come from YAML.

Use explicit `DATABASE_URL_DEVELOPMENT`, `DATABASE_URL_TEST`, or
`DATABASE_URL_PRODUCTION` only when the component `POSTGRES_*` fields are not
enough. Otherwise, `Settings.database_url_for(env)` assembles the URL.

## Documentation

- [Testing](docs/TESTING.md): fixture usage, test boundaries, and state cleanup.
- [Repositories And Services](docs/REPOSITORIES_SERVICES.md): DB layer, unit-of-work, and application service conventions.
- [Tools](docs/TOOLS.md): LangChain tool registration and async tool patterns.
- [Backends](docs/BACKENDS.md): memory, cache, and storage backend switching.
- [Graphs](docs/GRAPHS.md): graph builder conventions and config flow.
- [Jobs](docs/JOBS.md): job registration, runtime, retries, locks, status, and endpoints.
- [Admin Debug](docs/ADMIN_DEBUG.md): optional diagnostics endpoints and local inspection script.
- [Generator](docs/GENERATOR.md): CRUD resource scaffold command and generated-layer conventions.
- [Frontend](docs/FRONTEND.md): optional React + TypeScript app, static serving, and feature conventions.
- [Agent Smith Cutover](docs/AGENT_SMITH_CUTOVER.md): production preflight, cutover gates, and rollback boundary.
- [Deployment](docs/DEPLOYMENT.md): environment, migration, and runtime checklist.
- [Doctor Command](docs/DOCTOR.md): bootstrap checks for local and provider setup.
- [Security Automation](docs/SECURITY_AUTOMATION.md): dependency updates, audit scans, and secret scanning.
- [API Errors](docs/API_ERRORS.md): error envelope, request IDs, and debug error disclosure.
- [Authorization](docs/AUTHORIZATION.md): RBAC, scoped authorization, ownership checks, and audit sinks.
- [Database Patterns](db/PATTERNS.md): SQLAlchemy pitfalls worth keeping explicit.

Prefer updating the source-of-truth file over repeating details in documentation.
Add docs only when they explain a convention, tradeoff, or workflow that the code
does not make obvious.

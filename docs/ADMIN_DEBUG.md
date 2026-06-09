# Admin Debug Utilities

Cairn keeps diagnostics off by default. Enable them only for trusted
development or protected admin environments through the `admin_debug` config in
`config/default.yaml` and `config/models.py`.

Source of truth:

- Inspectors and redaction: `src/diagnostics/`
- Optional HTTP router: `src/diagnostics/router.py`
- Local CLI script: `scripts/inspect.py`
- Admin gate: `src.policies.dependencies.require_permission`
- Job runtime data: `src/jobs/runner.py`

The HTTP routes mount under `/admin/debug` only when `admin_debug.enabled=true`.
When `admin_debug.require_admin=true`, the routes require the existing admin
permission dependency. Config values stay redacted unless
`admin_debug.expose_config_values=true`; production validation rejects exposed
debug config values.

Local inspection uses the same inspectors as the HTTP routes:

```bash
poetry run python -m scripts.inspect config
poetry run python -m scripts.inspect registries
poetry run python -m scripts.inspect migrations
poetry run python -m scripts.inspect backends
```

Diagnostics are intentionally read-only. They report configuration snapshots,
registered services/tools/jobs/routers, Alembic current/head status, and safe
backend health checks without becoming a second configuration system.

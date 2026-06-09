# Agent Smith Cutover

Agent Smith runs inside Cairn when `AGENT_SMITH_ENABLED=true`. The production database and vector store remain the source of truth during cutover.

## Preflight

Run the preflight before changing traffic:

```bash
poetry run python scripts/agent_smith_preflight.py --production --output tmp/agent-smith-preflight.json
```

The script must report:

- `status: pass`
- `alembic_versions: ["7c1f9a2b3d4e"]`
- row counts for every Agent Smith table
- vector backend status or explicit credential-gated limitation

Production read-only checks require `AGENT_SMITH_PROD_DATABASE_URL_READONLY`.

## Cutover Gates

Do not deploy a write-capable cutover unless all are true:

- a database backup path is recorded in `AGENT_SMITH_BACKUP_PATH`
- `AGENT_SMITH_CUTOVER_CONFIRMED=true`
- high-severity backend and frontend audits are clean
- the raw-SQL static gate has no production runtime matches
- local smoke checks pass for API, MCP, frontend, scheduler, memory, sync, and eval routes

Real agent home-directory sync is disabled unless `AGENT_SMITH_SYNC_ALLOW_REAL_TARGETS=true`. Keep `AGENT_SMITH_SYNC_ROOT` set for sandbox sync rehearsals.

## Blue-Green Rollback

Keep the old Agent Smith deployment available until the Cairn port passes post-cutover smoke checks. If health, `/api/*`, `/mcp/*`, frontend workflows, job execution, memory, or sync smoke fails after switching traffic, redeploy the old Agent Smith app against the unchanged production stores.

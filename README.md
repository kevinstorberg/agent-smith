<img src="assets/agent_smith_logo_white_thick.svg" alt="AgentSmith" width="120" align="left" style="margin-right: 20px; margin-bottom: 10px;"/>

# agent-smith

A single harness for managing rules, skills, and MCP servers across multiple AI coding agents.
One source of truth, synced everywhere.

## Quick Start

```sh
./setup.sh                   # once: Python + frontend dependencies
./run.sh
```

Requires Python 3.13 and Node 22.12 or newer. `./setup.sh` installs into `.venv`
and `services/client/node_modules`; subsequent launches reuse those dependencies.
`./run.sh` starts production: it builds the frontend only when source inputs change,
then serves the dashboard + API + MCP on port 7654. If this checkout's instance of the
same mode is already running, `./run.sh` gracefully stops it first and relaunches; a
launch whose configuration fails validation leaves the running instance untouched.
Generate the ERD separately with `./erd.sh` (requires native Graphviz).

```sh
./run.sh dev                 # API with reload on 7655, Vite UI on 4321
./run.sh -d                  # production in the background (restarts it if running)
./run.sh --status            # inspect production process
./run.sh --stop              # graceful shutdown of this checkout's production process
./run.sh dev --stop          # stop development
./run.sh -nc                 # force frontend rebuild; also accepts --rebuild
```

Launch modes select `.env.development` and `.env.production` respectively. Override
ports with `DASHBOARD_PORT` and `DEV_FRONTEND_PORT`. Servers bind to loopback by
default; set `DASHBOARD_HOST` explicitly for remote access. Background launch reports
that startup has begun; inspect `.runtime/<environment>.log` for readiness/failures.
Use separate checkouts for active development and production so dependency refreshes
and frontend builds cannot alter the deployed checkout.

Agents connect to the MCP endpoint at `http://localhost:<DASHBOARD_PORT>/mcp/`.

## Structure

```text
assets/              # static assets (images, etc.)
docs/                # generated artifacts (ERD, etc.)
evals/               # LLM-as-judge evaluation framework (DeepEval + G-Eval)
scripts/             # sync, generation, and shared utilities
services/
  api/               # FastAPI app, routers, models, validators
  chat/              # shared Chat Rooms service and agent MCP tools
  client/            # React dashboard (Vite + TypeScript)
  db/                # Postgres connection + Alembic migrations
  memory/            # vector memory + MCP tools (pgvector, LanceDB, or Pinecone)
```

## Harness

Rules, skills, tools, hooks, and sub-agents are stored in Postgres with versioning and
per-agent assignment. Each item has one or more **deployment configs** (`harness_configs`)
that control where it syncs — scoped by device (`DEVICE_NAME`) and repo (absolute path).
Configs can be additive (include) or subtractive (exclude). Managed via the dashboard UI
or MCP tools.

## Sync

```sh
./sync.sh
```

Reads harness items from the database, resolves deployment configs, and writes to each
agent's config files — globally (`~/.claude/`, `~/.codex/`, `~/.gemini/`) or per-repo
(e.g., `<repo>/.claude/rules/`).

- **compose** — concatenates rules into a single markdown file
- **copy** — syncs skill subdirectories to the agent's skills directory
- **merge** — merges MCP server configs into the agent's settings file
- **agents** — syncs sub-agent definitions as markdown files with YAML frontmatter

Supports Claude, Codex, and Gemini. Only writes when content has changed. Set
`DEVICE_NAME` in your environment's `.env.*` file to enable device-scoped filtering.

## Memory

Vector memory with time-weighted retrieval, served as MCP tools on the dashboard endpoint.
Defaults to LanceDB (local, stored in `memory_store/`). The supported backends are
`lancedb`, `pinecone`, and `pgvector`. The pgvector backend uses the existing
`DATABASE_URL_<ENV>` database and the Alembic-managed `memories` table:

```env
MEMORY_BACKEND=pgvector
MEMORY_EMBEDDING_MODEL=all-MiniLM-L6-v2
MEMORY_EMBEDDING_DIMENSION=384
```

The model and dimension form one storage contract. Changing either requires a schema and
data migration; startup fails if stored rows use a different model or the database column
has a different dimension. pgvector retrieval uses exact cosine distance, so no approximate
index needs to be trained before cutover. Keep `MEMORY_BACKEND=pinecone` during the data
migration and change the production backend only after reconciliation passes.

## Background Jobs

Scheduled shell commands that run on a fixed interval, managed via the dashboard (the
**Jobs** tab) or MCP tools. Each job stores a `schedule_config` interval (e.g.
`{"minutes": 5}`) and an `input_params.command`. Like harness items, jobs carry
**deployment configs** (`job_configs`) scoping them by device (`DEVICE_NAME`) and repo with
additive (include) / subtractive (exclude) rules — a job only runs on a device its configs
select.

A pure-asyncio scheduler runs inside the dashboard process (started in the app lifespan): it
polls for due jobs, executes each command in a subprocess with a timeout, and records every
run in `job_executions` (status, timing, stdout/stderr, exit code). Executions left
`running` when the app stops are reconciled to `interrupted` on the next startup. Trigger an
immediate run with **Run Now** (or the `job_run_now` MCP tool), which ignores the schedule
and scoping.

Tune `JOB_POLL_INTERVAL`, `JOB_DEFAULT_TIMEOUT`, and `JOB_MAX_OUTPUT_BYTES` in your
environment's `.env.*` file.

## Chat Rooms

The **Chat** page provides a shared transcript for the User and already-open Claude,
Codex, or Gemini coding sessions. Create a room, copy that agent's invite prompt into
its existing session, and use the dashboard composer as the User. Agents participate
through the `chat_read` and `chat_post` MCP tools, preserving the repository context
and tools they already have.

**Stop Agent Access** closes the room immediately to new messages and tells polling
agents to stop. Closing is irreversible; the transcript remains readable. It cannot
cancel an inference an agent had already started before the room was closed.

**AI participants** are additional LLM seats configured by the index-aligned
`CHAT_MODEL_NAMES` / `CHAT_MODEL_IDS` env lists (see `.env.default`). Mention one by
name in a User message — `@Kimi`, case-insensitive — and it posts one reply into the
room via the `chat` graph. Only User messages trigger mentions, so agents and AI
participants can never summon each other into a loop; agents can still summon one
deliberately with `run_graph("chat", {"room_id": N, "participant": "Kimi"})`. Each
participant name is also its stored message author, so pick names that don't collide
with `user`/`claude`/`codex`/`gemini` (enforced at startup). The graphs MCP server
must be restarted to refresh the `run_graph` tool description after changing graphs.

## Tests

```sh
./audit.sh
```

Runs backend tests (pytest) and frontend tests (Vitest). Pytest flags are forwarded:
`./audit.sh -x` stops on first failure, `./audit.sh -k test_plans` filters by name.

Install native PostgreSQL 17 and pgvector for tests. Set `POSTGRES_BIN` to the server
bin directory if it is not on PATH (Homebrew example: `$(brew --prefix postgresql@17)/bin`).
`./audit.sh` initializes a fresh cluster on a random loopback port, runs backend
tests with a temporary local memory store, and stops/removes only that owned cluster.
It never resets, drops, or connects to your configured application databases. CI uses
this same native backend audit command; no container runtime is required.

For direct `pytest tests/` invocations, set `APP_ENV=test` and `DATABASE_URL_TEST`
to a dedicated loopback database ending in `_test`. Remote targets and targets
matching configured production are rejected before connecting. Prefer `./audit.sh`
for automatic isolation.

## Evals

LLM-as-judge evaluation using DeepEval's G-Eval metric. Suites are defined in Postgres
and picked up automatically at test time.

```sh
./evals.sh                        # run all enabled suites
./evals.sh --suite rules_plans    # run a specific suite
```

Runs directly against the selected application database; the dashboard need not be
running. Defaults to production for compatibility; use `./evals.sh --env development`
to evaluate development suites. Evals intentionally record results in that database.
Configure via `EVAL_MODEL`, `EVAL_JUDGE_MODEL`, and `EVAL_THRESHOLD` in the selected
environment's `.env.*` file.

## Database

Postgres stores harness items, eval configs, eval results, plans, and—when
`MEMORY_BACKEND=pgvector`—memory content, metadata, and embeddings.
Schema is managed by Alembic. Development/test migrations run on startup. Production
startup only reads the migration revision and refuses incompatible schemas. Production
database creation and direct production Alembic commands (including downgrade) are
blocked. Forward upgrades require explicit database-name confirmation after review:

```sh
./db.sh development
./db.sh production --confirm-database <production-database-name>
```

Set `DATABASE_URL_DEVELOPMENT`, `DATABASE_URL_TEST`, or `DATABASE_URL_PRODUCTION`
in the corresponding `.env.*` file. Existing external production databases and data
remain in place. Install pgvector before initializing new local databases. Development
and test cannot select the configured production target.

For a new development database on an already running native PostgreSQL server, use
`APP_ENV=development .venv/bin/python -m services.db.create`, then `./run.sh dev`.
PostgreSQL is optional on the application host when the selected application database
already runs elsewhere; its native server binaries are required for isolated audits.

Application guards do not restrict arbitrary SQL clients. Use a production runtime
role that does not own schemas/tables and lacks database/schema creation permissions;
use separate credentials for reviewed migrations. This change does not alter existing
roles, grants, schemas, or production data.

## Environment

`.env.default` contains committed defaults. Each environment has its own override file
(`.env.development`, `.env.test`, `.env.production`) — all gitignored. Defaults are
overridden by the selected environment file, then explicit process variables.
`APP_ENV` defaults to development for Python entry points; `./run.sh` explicitly
selects production for compatibility. Local memory paths default to separate
`memory_store/<environment>` directories; shared production paths/indexes are rejected
in development and test.

See `.env.default` for all available configuration options.

## Existing installations

The code migration does not stop existing services or remove Docker volumes. Keep
those volumes and verified backups until native production has been checked. Existing
external PostgreSQL and Pinecone data stay in place; retain their URLs/backend settings.
For LanceDB, copy the existing `memory_store` volume while the old writer is stopped,
verify the copy, and set an absolute `MEMORY_STORE_PATH` in `.env.production`. Production
refuses an absent/empty store rather than silently starting with no memories. An entirely
new installation can use pgvector or a separately initialized LanceDB store.

Replace certificate paths such as `/certs/rds-global-bundle.pem` in database URLs with
the existing host certificate path. Keep TLS verification enabled. Recheck stored job
commands for Linux-specific tools and `/app` paths: native jobs run as the launching
user. Agent config files are accessed directly in that user's home directory. Only one
application process per environment is launched; do not add Uvicorn workers, because
the scheduler runs inside each application process. For persistence across reboots,
manage the production launcher through launchd/systemd under an appropriate user.

Existing development harness tools may contain MCP URLs for the old port 7654. Update
those development URLs before syncing to agents, or explicitly retain that port in
`.env.development` while production is stopped. The default production port stays 7654.

Native setup requires OS-specific prerequisites; the launcher does not install global
system packages or automatically change production infrastructure. Linux PostgreSQL
packages are documented by [PostgreSQL](https://www.postgresql.org/download/linux/ubuntu/),
and extension installation by [pgvector](https://github.com/pgvector/pgvector#installation).

# agent-smith

![agent-smith](assets/agent_smith.png)

A single harness for managing rules, skills, and MCP servers across multiple AI coding agents.
One source of truth, synced everywhere.

## Quick Start

```sh
./run.sh
```

This builds the Docker image, generates the ERD, and starts the dashboard + MCP
server. Use `./run.sh -nc` to force a no-cache rebuild. See `DASHBOARD_PORT` in
`.env.default` for the port (default 7654).

Agents connect to the MCP endpoint at `http://localhost:<DASHBOARD_PORT>/mcp/`.

## Structure

```text
assets/              # static assets (images, etc.)
docs/                # generated artifacts (ERD, etc.)
evals/               # LLM-as-judge evaluation framework (DeepEval + G-Eval)
scripts/             # sync, generation, and shared utilities
services/
  api/               # FastAPI app, routers, models, validators
  client/            # React dashboard (Vite + TypeScript)
  db/                # Postgres connection + Alembic migrations
  memory/            # vector memory + MCP tools (LanceDB + sentence-transformers)
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
Defaults to LanceDB (local, stored in `memory_store/`). Set `MEMORY_BACKEND=pinecone` in
`.env` with a `PINECONE_API_KEY` to use Pinecone instead.

## Tests

```sh
./audit.sh
```

Runs backend tests (pytest) and frontend tests (Vitest). Pytest flags are forwarded:
`./audit.sh -x` stops on first failure, `./audit.sh -k test_plans` filters by name.

CI runs both suites plus a Docker build validation. DB-dependent tests use a Postgres
service container in CI.

## Evals

LLM-as-judge evaluation using DeepEval's G-Eval metric. Suites are defined in Postgres
and picked up automatically at test time.

```sh
./evals.sh                        # run all enabled suites
./evals.sh --suite rules_plans    # run a specific suite
```

Requires the app container to be running (`./run.sh`). Configure via `EVAL_MODEL`,
`EVAL_JUDGE_MODEL`, and `EVAL_THRESHOLD` in your environment's `.env.*` file.

## Database

Postgres stores harness items, eval configs, eval results, plans, and memory metadata.
Schema is managed by Alembic. Migrations run automatically on app startup, or manually:

```sh
.venv/bin/alembic upgrade head
```

Set `DATABASE_URL` in `.env` to override the default (`postgresql://localhost/agent_smith`).

## Environment

`.env.default` contains committed defaults. Each environment has its own override file
(`.env.development`, `.env.test`, `.env.production`) — all gitignored. `.env.default` is
loaded first; the environment-specific file overrides it based on `APP_ENV` (default: `development`).

See `.env.default` for all available configuration options.

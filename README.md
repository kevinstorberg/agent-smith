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

## Manual Setup (development without Docker)

```sh
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

brew install postgresql@17
brew services start postgresql@17
createdb agent_smith

.venv/bin/uvicorn services.dashboard.app:app --port 7654
```

Migrations and data seeding run automatically on startup.

## Structure

```text
assets/              # static assets (images, etc.)
docs/                # generated artifacts (ERD, etc.)
evals/               # LLM-as-judge evaluation framework (DeepEval + G-Eval)
scripts/             # migration, sync, and generation utilities
services/
  db/                # Postgres connection + Alembic migrations
  memory/            # vector memory + MCP tools (LanceDB + sentence-transformers)
  dashboard/         # web UI (FastAPI + React) + MCP endpoint
```

## Harness

Rules, skills, tools, hooks, and sub-agents are stored in Postgres with versioning and
per-agent assignment. Each item has one or more **deployment configs** (`harness_configs`)
that control where it syncs — scoped by device (`DEVICE_NAME`) and repo (absolute path).
Configs can be additive (include) or subtractive (exclude). Managed via the dashboard UI
or MCP tools.

## Sync

```sh
./sync.py
```

Reads harness items from the database, resolves deployment configs, and writes to each
agent's config files — globally (`~/.claude/`, `~/.codex/`, `~/.gemini/`) or per-repo
(e.g., `<repo>/.claude/rules/`).

- **compose** — concatenates rules into a single markdown file
- **copy** — syncs skill subdirectories to the agent's skills directory
- **merge** — merges MCP server configs into the agent's settings file
- **agents** — syncs sub-agent definitions as markdown files with YAML frontmatter

Supports Claude, Codex, and Gemini. Only writes when content has changed. Set
`DEVICE_NAME` in `.env` to enable device-scoped filtering.

## Memory

A local vector memory system with time-weighted retrieval via LangChain's
`TimeWeightedVectorStoreRetriever`. Served as MCP tools on the dashboard endpoint.

**CLI interface:**

```sh
./memory.py list [--repo REPO]         # browse memories
./memory.py search "QUERY" [--repo R]  # semantic search
./memory.py add "CONTENT" [--repo R] [--tags t1 t2]
./memory.py show ID
./memory.py delete ID
```

Default backend is LanceDB (local, stored in `memory_store/`). Set `MEMORY_BACKEND=pinecone`
in `.env` with a `PINECONE_API_KEY` to use Pinecone cloud instead.

## Tests

```sh
./audit.sh
```

Runs backend tests (pytest) and frontend tests (Vitest). Pytest flags are forwarded:
`./audit.sh -x` stops on first failure, `./audit.sh -k test_plans` filters by name.

CI runs both suites plus a Docker build validation. DB-dependent tests use a Postgres
service container in CI.

## Evals

LLM-as-judge evaluation using DeepEval's G-Eval metric. Eval suites and scenarios
are stored entirely in Postgres (`eval_suites` + `eval_scenarios` tables) and
discovered dynamically at test time. Results are stored in `eval_results`.

A single test runner handles all suites — no per-suite test files needed. New suites
added to the database are picked up automatically.

```sh
# Run a specific suite by name
docker compose exec app python -m pytest evals/test_suite.py --suite rules_plans -v

# Run all enabled suites
docker compose exec app python -m pytest evals/test_suite.py -v
```

Configure via `EVAL_MODEL`, `EVAL_JUDGE_MODEL`, and `EVAL_THRESHOLD` in `.env`.

## Database

Postgres stores harness items, eval configs, eval results, plans, and memory metadata.
Schema is managed by Alembic. Migrations run automatically on app startup, or manually:

```sh
.venv/bin/alembic upgrade head
```

Set `DATABASE_URL` in `.env` to override the default (`postgresql://localhost/agent_smith`).

## Environment

`.env.default` contains defaults and is committed. `.env` contains local overrides and is
gitignored. Both are loaded automatically (`.env` first, then `.env.default` fills gaps).

See `.env.default` for all available configuration options.

## Planned Features
- Additional agent model support (e.g. Mistral Code)
- Conversion into an open source library

# agent-smith

![agent-smith](assets/agent_smith.png)

A single harness for managing rules, skills, and MCP servers across multiple AI coding agents.
One source of truth, synced everywhere.

## Setup

```sh
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Structure

```text
assets/              # static assets (images, etc.)
evals/               # LLM-as-judge evaluation framework (DeepEval + G-Eval)
  config/            # eval suite configs (scenarios + judge prompts, migrated to DB)
scripts/             # migration and sync utilities
services/
  db/                # Postgres connection + Alembic migrations
  memory/            # vector memory MCP server (LanceDB + sentence-transformers)
  dashboard/         # web UI (FastAPI + React)
```

## Harness

Rules, skills, tools, and hooks are stored in Postgres with versioning, project scoping,
and per-agent assignment. Managed via the dashboard UI, MCP tools, or direct DB access.

## Sync

```sh
./sync.py
```

Reads harness items from the database and writes them to each agent's config files:

- **compose** — concatenates rules into a single markdown file
- **copy** — syncs skill subdirectories to the agent's skills directory
- **merge** — merges MCP server configs into the agent's settings file

Supports Claude, Codex, and Gemini. Only writes when content has changed.

## Memory

A local vector memory system with time-weighted retrieval via LangChain's
`TimeWeightedVectorStoreRetriever`.

**One-time setup:**

```sh
./memory.py init    # create the local database
./memory.py start   # start the MCP server and grant all agents access
```

`start` writes the MCP config to all agents via `./sync.py`. `stop` removes it.
The database persists across start/stop cycles.

**Human interface:**

```sh
./memory.py list [--repo REPO]         # browse memories
./memory.py search "QUERY" [--repo R]  # semantic search
./memory.py add "CONTENT" [--repo R] [--tags t1 t2]
./memory.py show ID
./memory.py delete ID
./memory.py status                     # check if server is running
```

Default backend is LanceDB (local, stored in `memory_store/`). Set `MEMORY_BACKEND=pinecone`
in `.env` with a `PINECONE_API_KEY` to use Pinecone cloud instead. The server runs on
`localhost:7367`.

## Tests

```sh
.venv/bin/pytest tests/ -v
```

## Evals

LLM-as-judge evaluation using DeepEval's G-Eval metric. Three eval suites:

- **rules/plans** — scores agent-generated plans against harness rules
- **skills/write_ticket** — scores generated tickets against ticket-writing criteria
- **skills/write_epic** — scores generated epics against epic-writing criteria

Eval suites and scenarios are stored in Postgres (`eval_suites` + `eval_scenarios` tables)
and loaded at test time. Results are stored in `eval_results`.

```sh
.venv/bin/pytest evals/ -v
```

Configure via `EVAL_MODEL`, `EVAL_JUDGE_MODEL`, and `EVAL_THRESHOLD` in `.env`.

## Database

Postgres stores harness items, eval configs, eval results, plans, and memory metadata.

```sh
brew install postgresql@17
brew services start postgresql@17
createdb agent_smith
```

Schema is managed by Alembic. Migrations run automatically on app startup, or manually:

```sh
.venv/bin/alembic upgrade head
```

Set `DATABASE_URL` in `.env` to override the default (`postgresql://localhost/agent_smith`).

## Dashboard

A local web UI for managing the harness and viewing eval results.

```sh
.venv/bin/uvicorn services.dashboard.app:app --port 7654
open http://localhost:7654
```

Sections: **Harness** (rules, skills, tools, hooks), **Memory** (semantic search + browse),
**Plans**, **Evals** (suite + scenario config), **Results** (score charts + run details).

For frontend development with hot reload:

```sh
cd services/dashboard/ui && npm install && npm run dev
```

## Environment

`.env.default` contains defaults and is committed. `.env` contains local overrides and is
gitignored. Both are loaded automatically (`.env` first, then `.env.default` fills gaps).

Disable individual MCP servers by setting `{Name}_ENABLED=false` in `.env`:

```sh
Slack_ENABLED=false
```

## Planned Features
- Additional agent model support (e.g. Mistral Code)
- Conversion into an open source library
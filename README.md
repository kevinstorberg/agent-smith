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
harness/
  main.md            # preamble prepended to every agent's rules file
  rules/             # behavioral directives (markdown, composed in order)
  skills/            # slash commands (one subdirectory per skill, each with SKILL.md)
  mcp/               # MCP server definitions (one JSON file per server)
evals/               # LLM-as-judge evaluation framework (DeepEval + G-Eval)
services/
  memory/            # local vector memory MCP server (LanceDB + sentence-transformers)
tmp/                 # scratch files and draft plans (gitignored contents)
```

Each harness category has a `shared/` subfolder (applied to all agents), per-agent subfolders
(`claude/`, `codex/`, `gemini/`), and a `local/` subfolder (gitignored, machine-specific).
Files within `rules/` and `mcp/` are processed in lexicographic order.

## Manifest

`harness.yaml` declares, for each agent and category, the target file/directory and which
source folders to pull from.

## Sync

```sh
./sync.py
```

Reads `harness.yaml` and applies three operations:

- **compose** — concatenates markdown files into a single rules file
- **copy** — syncs skill subdirectories to the agent's skills directory
- **merge** — merges MCP server JSON into the agent's config file

Only writes when content has changed.

## Memory

A local vector memory system with time-weighted retrieval. Recent and frequently
accessed memories are gently preferred over old ones via LangChain's
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

LLM-as-judge evaluation of rule compliance using DeepEval. Invokes a real CLI agent,
then scores its output against every rule in `harness/rules/shared/`.

```sh
.venv/bin/pytest evals/ -v
```

Configure via `EVAL_MODEL`, `EVAL_JUDGE_MODEL`, and `EVAL_THRESHOLD` in `.env`.
Results are saved to `evals/results/` (gitignored).

## Environment

`.env.default` contains defaults and is committed. `.env` contains local overrides and is
gitignored. Both are loaded automatically (`.env` first, then `.env.default` fills gaps).

Disable individual MCP servers by setting `{Name}_ENABLED=false` in `.env`:

```sh
Slack_ENABLED=false
```

## Planned Features
- Additional agent model support (e.g. Mistral Code)
- Repo/project scoped rules, skills, and tooling
- Conversion into an open source library
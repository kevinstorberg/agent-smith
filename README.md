# agent-smith

![agent-smith](assets/agent_smith.png)

A single harness for managing rules, skills, and MCP servers across multiple AI coding agents.
One source of truth, synced everywhere.

## Structure

```text
harness/
  main.md            # preamble prepended to every agent's rules file
  rules/             # behavioral directives (markdown, composed in order)
  skills/            # slash commands (one subdirectory per skill, each with SKILL.md)
  mcp/               # MCP server definitions (one JSON file per server)
```

Each category has a `shared/` subfolder (applied to all agents) and per-agent subfolders
(`claude/`, `codex/`, `gemini/`). Files within `rules/` and `mcp/` are processed in
lexicographic order.

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

A local vector memory system that agents can read and write across sessions.

**One-time setup:**

```sh
./memory.py init    # create the local database
./memory.py start   # start the MCP server and grant all agents access
```

`start` writes the MCP config, rules, and `/memory` skill to all agents via `./sync.py`.
`stop` removes them. The database persists across start/stop cycles.

**Human interface:**

```sh
./memory.py list [--repo REPO]         # browse memories
./memory.py search "QUERY" [--repo R]  # semantic search
./memory.py add "CONTENT" [--repo R] [--tags t1 t2]
./memory.py show ID
./memory.py delete ID
./memory.py status                     # check if server is running
```

Data is stored in `memory_store/` (gitignored). The server runs on `localhost:7367`.

## Environment

Copy `.env.local` to `.env` for API keys and other secrets. `.env` is gitignored.

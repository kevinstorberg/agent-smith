# agent-smith

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

## Environment

Copy `.env.local` to `.env` for API keys and other secrets. `.env` is gitignored.

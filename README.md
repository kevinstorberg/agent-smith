# agent-smith

A single harness for managing rules, skills, and tools across multiple AI coding agents. One source of truth, synced everywhere.

## Structure

```
harness/
  rules/       # behavioral directives and principles
  skills/      # slash commands and capabilities
  tools/       # MCP server configurations
```

Each category has a `shared/` subfolder (applied to all agents) and per-agent subfolders (`claude/`, `codex/`, `gemini/`, etc). Files within each folder are composed in lexicographic order — use numeric prefixes (`01-`, `02-`) to control ordering.

## Manifest

`harness.yaml` declares, for each agent, the target config file and which folders compose into it. This is the contract between the harness content and the sync process.

## Sync

```
python sync.py
```

Reads `harness.yaml`, assembles each agent's config from the declared folders, and writes the result to the agent's target file. Only writes when content has changed.

## Environment

Copy `.env.local` to `.env` for API keys and other secrets. `.env` is gitignored.
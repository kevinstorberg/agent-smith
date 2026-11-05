# Repository cleanup tool

The `repos` harness tool runs locally through MCP stdio, using the same cleanup
engine as `scripts/repos.py`. It is not exposed through the dashboard HTTP server.

After merging the cleanup CLI and MCP integration PRs and updating your local
Agent Smith checkout, register it once in the environment your app uses:

```sh
APP_ENV=production .venv/bin/python scripts/repos_tool.py init
```

The tool appears under Harness → Tools as `repos`. Existing custom metadata and
disabled deployment settings are preserved when registration is repeated. Use
the tool's existing Sync action to deploy it to your agents, then reconnect the
agent's MCP client.

The shared configuration stores `${AGENT_SMITH_ROOT}` and
`${AGENT_SMITH_PYTHON}`. Sync resolves these to that device's canonical Agent Smith
checkout and its `.venv/bin/python`, including when sync runs from a temporary
worktree. It does not copy another device's interpreter or a temporary worktree
path into the shared tool record.

Call `cleanup_merged_worktrees` with an absolute `repository_path`. Its defaults
only preview candidates:

```json
{"repository_path":"/absolute/path/to/repository"}
```

To carry out an explicitly requested cleanup, set `execute: true`. Set
`force: true` to discard dirty changes in verified merged worktrees. Set
`delete_remote: true` separately to remove verified origin branches as well.
Protected branches, active or locked worktrees, merely closed PRs and commits
outside merged PR evidence remain protected. Review each item's reported reason.

The machine running the tool needs Git, authenticated GitHub CLI and `lsof`.
Cleanup does not pull, switch branches, stop processes or restart Agent Smith.

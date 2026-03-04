#!/usr/bin/env -S .venv/bin/python3
"""
memory.py — CLI for managing agent long-term memory.

Usage:
  ./memory.py init                                # one-time: create the memory store
  ./memory.py start [--daemon] [--port N]         # start MCP server + grant agents access
  ./memory.py stop                                # stop server + revoke agent access
  ./memory.py status                              # print server running/stopped
  ./memory.py list [--repo REPO] [--limit N]
  ./memory.py search QUERY [--repo REPO] [--limit N]
  ./memory.py add CONTENT [--repo REPO] [--tags t1 t2 ...]
  ./memory.py delete ID
  ./memory.py show ID
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.resolve()
PID_FILE = REPO_ROOT / "memory.pid"
MCP_LOCAL_DIR = REPO_ROOT / "harness" / "mcp" / "local"
RULES_LOCAL_DIR = REPO_ROOT / "harness" / "rules" / "local"
SKILLS_LOCAL_DIR = REPO_ROOT / "harness" / "skills" / "local" / "memory"

DEFAULT_PORT = 7367


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db():
    """Lazy import so the CLI is usable even before chromadb is installed."""
    sys.path.insert(0, str(REPO_ROOT))
    from services.memory import db
    return db


def _print_memory(mem: dict, *, verbose: bool = False) -> None:
    score = f"  score={mem['score']:.4f}" if "score" in mem else ""
    repo = f"  repo={mem['repo']}" if mem.get("repo") else ""
    tags = f"  tags={mem['tags']}" if mem.get("tags") else ""
    print(f"[{mem['id']}]{score}{repo}{tags}")
    if verbose:
        print(f"  created: {mem['created_at']}")
        print(f"  updated: {mem['updated_at']}")
    print(f"  {mem['content']}")
    print()


def _running_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)  # signal 0 = existence check
        return pid
    except (ProcessLookupError, ValueError):
        PID_FILE.unlink(missing_ok=True)
        return None


def _write_harness_files(port: int) -> None:
    """Create the local harness files that grant agents access to the memory server."""
    url = f"http://localhost:{port}/mcp/"

    MCP_LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    (MCP_LOCAL_DIR / "memory.json").write_text(
        json.dumps({"name": "memory", "url": url}, indent=2) + "\n"
    )

    RULES_LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    (RULES_LOCAL_DIR / "memory.md").write_text(
        """\
## Long-Term Memory

You have access to a persistent memory system via MCP tools. Use it to preserve and recall
context across sessions.

**When to search:** At the start of work on any project, call `memory_search` with relevant
keywords and the repo name to surface prior decisions, patterns, and learnings.

**When to store:** After solving a non-obvious problem, discovering a project-specific pattern,
or making an architectural decision, call `memory_add` with the content scoped to the repo.

**Tagging:** Use concise tags (e.g. `["architecture", "auth", "bug"]`) to make memories easier
to filter later.

**Example workflow:**
```
memory_search(query="auth flow", repo="my-app")
# ... do work ...
memory_add(content="JWT tokens expire after 1h; refresh tokens stored in httpOnly cookies",
           repo="my-app", tags=["auth", "security"])
```
"""
    )

    SKILLS_LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    (SKILLS_LOCAL_DIR / "SKILL.md").write_text(
        """\
---
name: memory
description: >
  Search long-term memory for context relevant to the current task, then store key learnings
  after completing work. Use when starting on a project or before making significant decisions.
---

1. **Recall**: `memory_search(query="<relevant topic>", repo="<current-repo>")` to surface
   prior decisions and patterns. Briefly summarize what was found before proceeding.

2. **Work**: Complete the task using recalled context where relevant.

3. **Store**: After completing significant work, call `memory_add` to preserve key learnings:
   - Architectural decisions and their rationale
   - Non-obvious patterns discovered in the codebase
   - Solutions to hard problems that recur
   - Anything a future agent session should know about this project
"""
    )


def _delete_harness_files() -> None:
    """Remove the local harness files to revoke agent access."""
    for path in [
        MCP_LOCAL_DIR / "memory.json",
        RULES_LOCAL_DIR / "memory.md",
        SKILLS_LOCAL_DIR / "SKILL.md",
    ]:
        path.unlink(missing_ok=True)


def _run_sync() -> None:
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "sync.py")],
        cwd=str(REPO_ROOT),
        check=True,
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> None:
    db = _db()
    db.init()
    print("Memory store initialised at memory_store/")
    print("Run './memory.py start' to start the MCP server and grant agents access.")


def cmd_start(args: argparse.Namespace) -> None:
    if _running_pid():
        print(f"Memory server is already running (PID {_running_pid()}).")
        return

    _write_harness_files(args.port)
    _run_sync()
    print(f"[memory] harness files written and synced to all agents")

    server_script = REPO_ROOT / "services" / "memory" / "server.py"
    cmd = [sys.executable, str(server_script), "--port", str(args.port)]

    if args.daemon:
        proc = subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        PID_FILE.write_text(str(proc.pid))
        print(f"[memory] server started (PID {proc.pid}) on port {args.port}")
    else:
        print(f"[memory] starting server on port {args.port} (Ctrl-C to stop)")
        try:
            proc = subprocess.Popen(cmd, cwd=str(REPO_ROOT))
            PID_FILE.write_text(str(proc.pid))
            proc.wait()
        finally:
            PID_FILE.unlink(missing_ok=True)
            _delete_harness_files()
            _run_sync()
            print("\n[memory] server stopped; agents no longer have access")


def cmd_stop(args: argparse.Namespace) -> None:
    pid = _running_pid()
    if not pid:
        print("Memory server is not running.")
    else:
        os.kill(pid, signal.SIGTERM)
        PID_FILE.unlink(missing_ok=True)
        print(f"[memory] server stopped (PID {pid})")

    _delete_harness_files()
    _run_sync()
    print("[memory] harness files removed; agents no longer have access")


def cmd_status(args: argparse.Namespace) -> None:
    pid = _running_pid()
    if pid:
        print(f"running  (PID {pid})")
    else:
        print("stopped")


def cmd_list(args: argparse.Namespace) -> None:
    db = _db()
    memories = db.list_memories(repo=args.repo, limit=args.limit)
    if not memories:
        print("No memories yet.")
        return
    for mem in memories:
        _print_memory(mem)


def cmd_search(args: argparse.Namespace) -> None:
    db = _db()
    results = db.search(query=args.query, repo=args.repo, limit=args.limit)
    if not results:
        print("No results.")
        return
    for mem in results:
        _print_memory(mem)


def cmd_add(args: argparse.Namespace) -> None:
    db = _db()
    id = db.add(content=args.content, repo=args.repo, tags=args.tags or [])
    print(f"Added: {id}")


def cmd_delete(args: argparse.Namespace) -> None:
    db = _db()
    try:
        db.delete(args.id)
        print(f"Deleted: {args.id}")
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_show(args: argparse.Namespace) -> None:
    db = _db()
    mem = db.get(args.id)
    if not mem:
        print(f"Not found: {args.id}", file=sys.stderr)
        sys.exit(1)
    _print_memory(mem, verbose=True)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="memory.py",
        description="Manage agent long-term memory",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="One-time: create the memory store")

    start_p = sub.add_parser("start", help="Start the MCP server and grant agents access")
    start_p.add_argument("--daemon", action="store_true", help="Run in background")
    start_p.add_argument("--port", type=int, default=DEFAULT_PORT)

    sub.add_parser("stop", help="Stop the MCP server and revoke agent access")
    sub.add_parser("status", help="Print server running/stopped")

    list_p = sub.add_parser("list", help="List recent memories")
    list_p.add_argument("--repo", default=None)
    list_p.add_argument("--limit", type=int, default=20)

    search_p = sub.add_parser("search", help="Search memories semantically")
    search_p.add_argument("query")
    search_p.add_argument("--repo", default=None)
    search_p.add_argument("--limit", type=int, default=10)

    add_p = sub.add_parser("add", help="Add a new memory")
    add_p.add_argument("content")
    add_p.add_argument("--repo", default=None)
    add_p.add_argument("--tags", nargs="*", default=[])

    del_p = sub.add_parser("delete", help="Delete a memory by ID")
    del_p.add_argument("id")

    show_p = sub.add_parser("show", help="Show a memory by ID")
    show_p.add_argument("id")

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "init": cmd_init,
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
        "list": cmd_list,
        "search": cmd_search,
        "add": cmd_add,
        "delete": cmd_delete,
        "show": cmd_show,
    }
    dispatch[args.command](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

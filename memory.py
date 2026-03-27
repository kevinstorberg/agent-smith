#!/usr/bin/env -S .venv/bin/python3

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from scripts.shared.paths import REPO_ROOT

PID_FILE = REPO_ROOT / "memory.pid"
MCP_LOCAL_DIR = REPO_ROOT / "harness" / "mcp" / "local"

DEFAULT_PORT = 7367




def _db():
    """Lazy import so the CLI is usable before heavy deps are loaded."""
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
        os.kill(pid, 0)
        return pid
    except (ProcessLookupError, ValueError):
        PID_FILE.unlink(missing_ok=True)
        return None


def _write_harness_files(port: int) -> None:
    url = f"http://localhost:{port}/mcp/"

    MCP_LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    (MCP_LOCAL_DIR / "memory.json").write_text(
        json.dumps({"name": "memory", "url": url}, indent=2) + "\n"
    )


def _delete_harness_files() -> None:
    (MCP_LOCAL_DIR / "memory.json").unlink(missing_ok=True)


def _run_sync() -> None:
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "sync.py")],
        cwd=str(REPO_ROOT),
        check=True,
    )




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
        log_path = REPO_ROOT / "memory.log" if os.environ.get("MEMORY_LOG", "").lower() == "true" else os.devnull
        with open(log_path, "w") as out:
            proc = subprocess.Popen(
                cmd,
                cwd=str(REPO_ROOT),
                stdout=out,
                stderr=out,
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

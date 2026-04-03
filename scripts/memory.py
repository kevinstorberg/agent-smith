#!/usr/bin/env -S .venv/bin/python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.shared.paths import REPO_ROOT


def _db():
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
        prog="scripts/memory.py",
        description="Manage agent long-term memory",
    )
    sub = p.add_subparsers(dest="command", required=True)

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

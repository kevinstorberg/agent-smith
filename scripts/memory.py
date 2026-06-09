#!/usr/bin/env -S .venv/bin/python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) in sys.path:
    sys.path.remove(str(SCRIPT_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.agent_smith.services.memory import get_memory_service


def _print_memory(memory: dict, *, verbose: bool = False) -> None:
    score = f"  score={memory['score']:.4f}" if "score" in memory else ""
    repo = f"  repo={memory['repo']}" if memory.get("repo") else ""
    tags = f"  tags={memory['tags']}" if memory.get("tags") else ""
    print(f"[{memory['id']}]{score}{repo}{tags}")
    if verbose:
        print(f"  created: {memory['created_at']}")
        print(f"  updated: {memory['updated_at']}")
    print(f"  {memory['content']}")
    print()


def cmd_list(args: argparse.Namespace) -> None:
    memories = get_memory_service().list_memories(repo=args.repo, limit=args.limit)
    if not memories:
        print("No memories yet.")
        return
    for memory in memories:
        _print_memory(memory)


def cmd_search(args: argparse.Namespace) -> None:
    results = get_memory_service().search(query=args.query, repo=args.repo, limit=args.limit)
    if not results:
        print("No results.")
        return
    for memory in results:
        _print_memory(memory)


def cmd_add(args: argparse.Namespace) -> None:
    memory_id = get_memory_service().add(content=args.content, repo=args.repo, tags=args.tags or [])
    print(f"Added: {memory_id}")


def cmd_delete(args: argparse.Namespace) -> None:
    try:
        get_memory_service().delete(args.id)
        print(f"Deleted: {args.id}")
    except KeyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_show(args: argparse.Namespace) -> None:
    memory = get_memory_service().get(args.id)
    if not memory:
        print(f"Not found: {args.id}", file=sys.stderr)
        sys.exit(1)
    _print_memory(memory, verbose=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scripts/memory.py", description="Manage agent long-term memory")
    subcommands = parser.add_subparsers(dest="command", required=True)

    list_parser = subcommands.add_parser("list", help="List recent memories")
    list_parser.add_argument("--repo", default=None)
    list_parser.add_argument("--limit", type=int, default=20)

    search_parser = subcommands.add_parser("search", help="Search memories semantically")
    search_parser.add_argument("query")
    search_parser.add_argument("--repo", default=None)
    search_parser.add_argument("--limit", type=int, default=10)

    add_parser = subcommands.add_parser("add", help="Add a new memory")
    add_parser.add_argument("content")
    add_parser.add_argument("--repo", default=None)
    add_parser.add_argument("--tags", nargs="*", default=[])

    delete_parser = subcommands.add_parser("delete", help="Delete a memory by ID")
    delete_parser.add_argument("id")

    show_parser = subcommands.add_parser("show", help="Show a memory by ID")
    show_parser.add_argument("id")

    return parser


def main() -> int:
    args = build_parser().parse_args()
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

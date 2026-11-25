#!/usr/bin/env -S .venv/bin/python3

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.shared.validation import validate_memory_id


def _positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def _nonnegative_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a nonnegative integer") from None
    if number < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return number


def _positive_seconds(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a finite positive number") from None
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return number


def _memory_id(value: str) -> str:
    try:
        validate_memory_id(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a memory UUID") from None
    return value.lower()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Explicitly initialize or repair the Pinecone memory listing index.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("initialize", "repair", "abort-build"):
        command = commands.add_parser(name)
        command.add_argument("--confirm-index", required=True)
        command.add_argument(
            "--confirm-namespace",
            required=True,
            help="Use __default__ for the application's default namespace.",
        )
        command.add_argument(
            "--confirm-quiescent-writers",
            action="store_true",
            required=True,
            help="Confirm old application and external writers are stopped.",
        )
        if name == "abort-build":
            command.add_argument(
                "--confirm-initializer-stopped", action="store_true", required=True
            )
            command.set_defaults(max_records=1, max_requests=1, deadline_seconds=30)
        else:
            command.add_argument("--max-records", type=_positive_integer, required=True)
            command.add_argument(
                "--max-requests", type=_positive_integer, required=True
            )
            command.add_argument(
                "--deadline-seconds", type=_positive_seconds, required=True
            )
        command.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate configuration and report the operation without database or provider I/O.",
        )
        if name == "initialize":
            command.add_argument(
                "--expected-count", type=_nonnegative_integer, required=True
            )
        elif name == "repair":
            command.add_argument(
                "--id", type=_memory_id, action="append", required=True
            )
    return parser


def _components():
    from types import SimpleNamespace

    from services.config import PINECONE_INDEX
    from services.memory import catalog, db, maintenance

    if os.environ.get("MEMORY_BACKEND", "lancedb") != "pinecone":
        raise ValueError("The configured memory backend must be Pinecone")
    return SimpleNamespace(
        catalog=catalog,
        maintenance=maintenance,
        project=db.catalog_metadata,
        source=catalog.Source(PINECONE_INDEX),
    )


def _report(stage: str, source, **counts) -> None:
    print(
        json.dumps(
            {
                "stage": stage,
                "source": {
                    "index": source.index_name,
                    "namespace": source.namespace,
                },
                **counts,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def _validate(args, components) -> None:
    source = components.catalog.Source(args.confirm_index, args.confirm_namespace)
    if source != components.source:
        raise ValueError("Confirmed source does not match the configured memory source")
    if args.command == "initialize" and args.expected_count > args.max_records:
        raise ValueError("Expected count exceeds the record budget")
    if args.command == "repair":
        if len(set(args.id)) != len(args.id):
            raise ValueError("Repair IDs must be unique")
        if len(args.id) > args.max_records:
            raise ValueError("Repair IDs exceed the record budget")


@contextmanager
def _building(catalog, source, expected_count: int):
    build = catalog.begin_build(source, expected_count=expected_count)
    try:
        yield build
    except BaseException:
        try:
            catalog.fail_build(build)
        except Exception:
            print(
                "Memory catalog cleanup failed; the source remains unavailable until explicit maintenance.",
                file=sys.stderr,
            )
        raise


def _initialize(args, components, budget) -> int:
    catalog, maintenance, source = (
        components.catalog,
        components.maintenance,
        components.source,
    )
    budget.check()
    with _building(catalog, source, args.expected_count) as build:
        _report("building", source, expected_count=args.expected_count)
        budget.check()
        with maintenance.open_index(source, budget) as index:
            for rows in maintenance.iter_rows(index, budget):
                budget.check()
                catalog.stage_build(
                    build,
                    [components.project(row["id"], row["metadata"]) for row in rows],
                )
                budget.check()
        budget.check()
        return catalog.finish_build(build)


def _repair(args, components, budget) -> int:
    catalog, maintenance, source = (
        components.catalog,
        components.maintenance,
        components.source,
    )
    repaired = 0
    budget.reserve_records(len(args.id))
    _report("repairing", source, records=len(args.id))
    with ExitStack() as stack:
        index = None
        for id in args.id:
            budget.check()
            mutation = catalog.claim_repair(source, id, quiescent=True)
            budget.check()
            if not mutation.acknowledged:
                if index is None:
                    index = stack.enter_context(maintenance.open_index(source, budget))
                rows = maintenance.fetch_rows(index, [id], budget, strict=False)
                budget.check()
                metadata = components.project(id, rows[0]["metadata"]) if rows else None
                catalog.acknowledge(mutation, metadata)
                budget.check()
            catalog.finalize(mutation)
            repaired += 1
            budget.check()
    return repaired


def _execute(args, components) -> int:
    budget = components.maintenance.MaintenanceBudget(
        max_records=args.max_records,
        max_requests=args.max_requests,
        deadline_seconds=args.deadline_seconds,
    )
    try:
        if args.command == "initialize":
            count = _initialize(args, components, budget)
        elif args.command == "repair":
            count = _repair(args, components, budget)
        else:
            components.catalog.abort_build(components.source, quiescent=True)
            count = 0
    except Exception as error:
        if isinstance(error, TimeoutError):
            reason = "deadline_exceeded"
        elif isinstance(error, components.maintenance.BudgetExceeded):
            reason = "budget_exceeded"
        elif isinstance(error, components.catalog.Conflict):
            reason = "catalog_conflict"
        elif isinstance(error, components.catalog.Unavailable):
            reason = "catalog_unavailable"
        else:
            reason = "maintenance_failed"
        _report(
            "failed",
            components.source,
            records=budget.records,
            requests=budget.requests,
            reason=reason,
        )
        return 1
    _report(
        {
            "initialize": "ready",
            "repair": "repaired",
            "abort-build": "aborted",
        }[args.command],
        components.source,
        records=count,
        requests=budget.requests,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        components = _components()
        _validate(args, components)
    except (ValueError, RuntimeError):
        print(
            "Memory catalog configuration or source confirmation is invalid.",
            file=sys.stderr,
        )
        return 1
    if args.dry_run:
        _report(
            "validated",
            components.source,
            command=args.command,
            records=(
                args.expected_count
                if args.command == "initialize"
                else len(args.id)
                if args.command == "repair"
                else 0
            ),
            max_records=args.max_records,
            max_requests=args.max_requests,
            deadline_seconds=args.deadline_seconds,
        )
        return 0
    return _execute(args, components)


if __name__ == "__main__":
    raise SystemExit(main())

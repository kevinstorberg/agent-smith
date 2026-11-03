#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.shared.atomic_json import atomic_write_json
from scripts.shared.claude_memory_capture import CaptureStore, MAX_OUTPUT_BYTES
from scripts.shared.paths import REPO_ROOT


def probe(session_id: str, state_root: Path) -> dict:
    session_id = str(uuid.UUID(session_id))
    result = {
        "version": 1,
        "status": "probe_ready",
        "session_id": session_id,
        "nonce": uuid.uuid4().hex,
    }
    atomic_write_json(state_root / "probes" / f"{session_id}.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded context for the Claude memory agent hook")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("probe", help="Verify the hook can execute its context helper")
    check.add_argument("--session-id", required=True)
    for command in ("read", "ack", "fail", "status", "record-current"):
        child = commands.add_parser(command)
        child.add_argument("--session-id", required=True)
        if command == "read":
            child.add_argument("--transcript", required=True)
        if command in {"ack", "fail"}:
            child.add_argument("--receipt", required=True)
        if command == "ack":
            child.add_argument("--outcome", choices=["saved", "duplicate", "nothing_to_save"], required=True)
        if command in {"ack", "record-current"}:
            child.add_argument("--memory-id", action="append", default=[])
        if command == "fail":
            child.add_argument("--stage", required=True)
            child.add_argument("--error-code", required=True)
    args = parser.parse_args(argv)
    state_root = REPO_ROOT / ".runtime" / "claude-memory-capture"
    try:
        if args.command == "probe":
            result = probe(args.session_id, state_root)
        else:
            store = CaptureStore(Path.home() / ".claude" / "projects", state_root)
            if args.command == "read":
                result = store.read(args.session_id, args.transcript)
            elif args.command == "ack":
                result = store.acknowledge(args.session_id, args.receipt, args.outcome, args.memory_id)
            elif args.command == "fail":
                result = store.fail(args.session_id, args.receipt, args.stage, args.error_code)
            elif args.command == "record-current":
                result = store.record_current(args.session_id, args.memory_id)
            else:
                result = store.status(args.session_id)
    except (ValueError, OSError, RuntimeError):
        result = {"status": "error", "stage": args.command, "error_code": "helper_failed"}
    output = json.dumps(result, ensure_ascii=True)
    if len(output.encode("ascii")) > MAX_OUTPUT_BYTES:
        output = json.dumps({"status": "error", "stage": args.command, "error_code": "output_limit_exceeded"})
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

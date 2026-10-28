from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

from scripts.shared.env import read_env_file

ROOT = Path(__file__).resolve().parent.parent


def load_credentials() -> None:
    # Copy only meeting configuration/credentials, never the production DB target.
    settings = read_env_file(ROOT / ".env.production")
    raw = os.environ.get("MEETING_SOURCES_JSON", settings.get("MEETING_SOURCES_JSON", "{}"))
    os.environ.setdefault("MEETING_SOURCES_JSON", raw)
    try:
        sources = json.loads(raw)
    except ValueError:
        raise ValueError("MEETING_SOURCES_JSON must contain a JSON object") from None
    if not isinstance(sources, dict):
        raise ValueError("MEETING_SOURCES_JSON must contain a JSON object")
    for source in sources.values():
        if isinstance(source, dict) and isinstance(source.get("api_key_env"), str):
            key = source["api_key_env"]
            if key.startswith("DATABASE_URL") or key in {"APP_ENV", "MEETING_SOURCES_JSON", "MEMORY_STORE_PATH", "MEMORY_BACKEND"}:
                raise ValueError("Meeting api_key_env must reference a credential, not application configuration")
            if key in settings:
                os.environ.setdefault(key, settings[key])


async def probe(source: str) -> dict:
    from services.meetings.config import load_source_config
    from services.meetings.factory import build_meeting_provider

    started = time.monotonic()
    provider = build_meeting_provider(load_source_config(source))
    count, pages, summaries = 0, 0, 0
    cursor, seen = None, set()
    try:
        async with asyncio.timeout(240):
            while True:
                page = await provider.list_page(cursor)
                pages += 1
                count += len(page.notes)
                for reference in page.notes:
                    summary = await provider.get_summary(reference.external_id)
                    summaries += summary is not None
                cursor = page.next_cursor
                if cursor is None:
                    break
                if cursor in seen:
                    raise RuntimeError("Meeting provider returned a repeated cursor")
                seen.add(cursor)
        return {"source": source, "pages": pages, "listed": count, "summaries_validated": summaries,
                "elapsed_seconds": round(time.monotonic() - started, 2)}
    finally:
        await provider.aclose()


async def verify_live(source: str, stage: str) -> dict:
    from services.graphs.runtime import dispatch
    from services.meetings import db
    from services.meetings.config import load_source_config
    from services.meetings.factory import build_meeting_provider

    config = load_source_config(source)
    started = time.monotonic()
    if stage == "scan":
        from services.meetings.service import sync_source

        partial = await sync_source(source, run_budget_seconds=0.001)
        if partial.get("outcome") != "continued":
            raise RuntimeError("Live scan verification did not reach the bounded continuation state")
        status = db.source_status(source)
        if not status or not status[0]["scan_started_at"]:
            raise RuntimeError("Live scan verification did not retain a resumable checkpoint")
    graph_result = json.loads(await dispatch("meeting_ingest", {"source": source, "digest": False}))
    if stage == "scan":
        status = db.source_status(source)
        if not status or status[0]["scan_started_at"] or not status[0]["last_completed_at"]:
            raise RuntimeError("Live scan verification did not complete the resumed scan")
    listing = db.list_summaries(source=source)
    items, total = listing["items"], listing["total"]
    if not items:
        raise RuntimeError("Live meeting verification found no stored summaries")
    stored = items[0]
    if stage == "transcript":
        from services.meetings import digestion_db

        captured_id = graph_result.get("transcript", {}).get("meeting_id")
        stored = db.get_summary(captured_id) if captured_id else None
        if stored is None or (digestion_db.get_transcript(captured_id) or {}).get("status") != "ready":
            raise RuntimeError("Live transcript verification did not capture a complete transcript")
    provider = build_meeting_provider(config)
    try:
        summary = await provider.get_summary(stored["external_id"])
        if stage == "transcript":
            expected_segments, cursor, seen = [], None, set()
            async with asyncio.timeout(120):
                while True:
                    page = await provider.get_transcript_page(stored["external_id"], cursor)
                    start = len(expected_segments)
                    expected_segments.extend(segment.to_dict(start + index) for index, segment in enumerate(page.segments))
                    cursor = page.next_cursor
                    if cursor is None:
                        break
                    if cursor in seen:
                        raise RuntimeError("Live transcript cursor did not advance")
                    seen.add(cursor)
            record = digestion_db.get_record(stored["id"])
            if not expected_segments or record["transcript"]["segments"] != expected_segments:
                raise RuntimeError("Live transcript normalized readback mismatch")
    finally:
        await provider.aclose()
    if summary is None:
        raise RuntimeError("Live meeting verification could not retrieve the stored source note")
    expected = {
        "provider": config.provider,
        "account_key": config.account_key,
        "project": config.project,
        "external_id": summary.external_id,
        "title": summary.title,
        "summary_text": summary.summary_text,
        "summary_markdown": summary.summary_markdown,
        "source_url": summary.source_url,
        "metadata": summary.metadata,
        "provider_created_at": summary.provider_created_at.isoformat(),
        "provider_deleted_at": summary.provider_deleted_at.isoformat() if summary.provider_deleted_at else None,
    }
    if any(stored.get(field) != value for field, value in expected.items()):
        raise RuntimeError("Live meeting verification found a normalized summary mismatch")
    if stored["provider_updated_at"] != summary.provider_updated_at.isoformat():
        raise RuntimeError("Source note changed during live verification; rerun against a stable note")
    await dispatch("meeting_ingest", {"source": source, "digest": False})
    replay_total = db.list_summaries(source=source)["total"]
    matching = db.get_summary(stored["id"])
    if replay_total != total or matching is None or matching["revision"] != stored["revision"]:
        raise RuntimeError("Live meeting verification did not preserve identity/revision on replay")
    if stage == "context":
        from services.meetings.server import mcp

        response = await mcp.call_tool("meeting_get", {"summary_id": stored["id"]})
        content = response[0] if isinstance(response, tuple) else response
        if len(content) != 1 or json.loads(content[0].text) != matching:
            raise RuntimeError("Live context verification did not return the stored summary through MCP")
    result = {"source": source, "stage": stage, "stored": total, "normalized_summary_verified": True,
              "replay_verified": True, "graph_runs": 2,
              "elapsed_seconds": round(time.monotonic() - started, 2)}
    if stage == "scan":
        result["bounded_resume_verified"] = True
    if stage == "context":
        result["context_reader_verified"] = True
    if stage == "transcript":
        result.update(transcript_verified=True, transcript_segments=len(expected_segments))
    return result


def run_isolated(source: str, command: str, stage: str) -> dict:
    if "services.config" in sys.modules:
        raise RuntimeError("Isolated meeting verification must run in a fresh Python process")
    from scripts.shared.local_postgres import temporary_postgres

    with temporary_postgres() as url, TemporaryDirectory(prefix="agent-smith-meeting-memory-") as store:
        os.environ.update(APP_ENV="test", DATABASE_URL_TEST=url, MEMORY_BACKEND="lancedb", MEMORY_STORE_PATH=store)
        if command == "probe":
            return asyncio.run(probe(source))
        from services.db import close_pool, init_db
        from services.db.create import create_database

        create_database(url)
        try:
            init_db()
            return asyncio.run(verify_live(source, stage))
        finally:
            close_pool()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage meeting context imports")
    parser.add_argument("command", choices=["probe", "verify-live", "schedule"])
    parser.add_argument("--source", required=True)
    parser.add_argument("--isolated-db", action="store_true")
    parser.add_argument("--stage", choices=["one-summary", "scan", "context", "transcript"], default="one-summary")
    parser.add_argument("--device")
    parser.add_argument("--interval-minutes", type=float, default=15)
    args = parser.parse_args()
    if args.command == "verify-live" and not args.isolated_db:
        parser.error("verify-live requires --isolated-db; application databases are never verification targets")
    if args.command == "schedule":
        if not args.device or args.isolated_db:
            parser.error("schedule requires --device and cannot use --isolated-db")
        from services.db import init_db
        from services.meetings.schedule import configure_schedule

        init_db()
        job_id = configure_schedule(args.source, args.device, args.interval_minutes)
        print(json.dumps({"job_id": job_id, "source": args.source, "device": args.device}))
        return
    load_credentials()
    if args.isolated_db:
        result = run_isolated(args.source, args.command, args.stage)
    else:
        result = asyncio.run(probe(args.source))
    print(json.dumps(result))


if __name__ == "__main__":
    main()

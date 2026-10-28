from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone

import pytest

from scripts import meetings


def test_credentials_copy_only_configured_meeting_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", dict(os.environ))
    sources = {"work": {"provider": "granola", "account_key": "personal", "api_key_env": "MEETING_TEST_KEY"}}
    (tmp_path / ".env.production").write_text(
        f"MEETING_SOURCES_JSON={json.dumps(sources)}\n"
        "MEETING_TEST_KEY=private-fixture-key\n"
        "DATABASE_URL_PRODUCTION=never-load-this-target\n"
        "UNRELATED_API_KEY=never-load-this-key\n"
    )
    monkeypatch.setattr(meetings, "ROOT", tmp_path)
    for name in ("MEETING_SOURCES_JSON", "MEETING_TEST_KEY", "DATABASE_URL_PRODUCTION", "UNRELATED_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    meetings.load_credentials()
    assert json.loads(os.environ["MEETING_SOURCES_JSON"]) == sources
    assert os.environ["MEETING_TEST_KEY"] == "private-fixture-key"
    assert "DATABASE_URL_PRODUCTION" not in os.environ
    assert "UNRELATED_API_KEY" not in os.environ


@pytest.mark.parametrize("raw", ["false", '{"work":{"api_key_env":"DATABASE_URL_PRODUCTION"}}'])
def test_credentials_reject_nonobjects_and_database_references(monkeypatch, raw):
    monkeypatch.setenv("MEETING_SOURCES_JSON", raw)
    with pytest.raises(ValueError):
        meetings.load_credentials()


def test_live_verification_requires_isolation_before_loading_credentials(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["meetings", "verify-live", "--source", "work"])
    monkeypatch.setattr(meetings, "load_credentials", lambda: pytest.fail("Credentials loaded before isolation validation"))
    with pytest.raises(SystemExit) as error:
        meetings.main()
    assert error.value.code == 2
    assert "requires --isolated-db" in capsys.readouterr().err


def test_live_verification_selects_owned_database_before_importing_services_config():
    code = """
import json, os, sys
from scripts import meetings
assert 'services.config' not in sys.modules
os.environ['APP_ENV'] = 'production'
os.environ['DATABASE_URL_TEST'] = 'postgresql://invalid/test'
async def verify(source, stage):
    from services.config import APP_ENV, DATABASE_URL
    from services.db import get_connection
    assert APP_ENV == 'test'
    assert DATABASE_URL != 'postgresql://invalid/test'
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), to_regclass('public.meeting_summaries') IS NOT NULL")
        database, migrated = cursor.fetchone()
    return {'isolated': database == 'agent_smith_test', 'migrated': migrated}
meetings.verify_live = verify
print(json.dumps(meetings.run_isolated('fixture', 'verify-live', 'one-summary')))
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"isolated": True, "migrated": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["one-summary", "scan", "context"])
async def test_live_verification_discards_graph_output_and_keeps_summary_content_private(monkeypatch, stage):
    from services.graphs import runtime
    from services.meetings import db, factory, service
    from services.meetings.types import MeetingSummary

    monkeypatch.setenv("MEETING_SOURCES_JSON", json.dumps({
        "fixture": {"provider": "granola", "account_key": "personal", "api_key_env": "MEETING_TEST_KEY"},
    }))
    monkeypatch.setenv("MEETING_TEST_KEY", "private-fixture-key")
    summary = MeetingSummary(
        external_id="fixture-note", title="Private meeting title", summary_text="Private meeting content",
        summary_markdown=None, source_url="https://example.test/note",
        provider_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        provider_updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        metadata={"private-fixture-metadata": "sensitive"},
    )
    row = {key: value.isoformat() if isinstance(value, datetime) else value for key, value in asdict(summary).items()}
    row.update(id="fixture-id", revision=1, provider="granola", account_key="personal", project=None)
    calls = []

    async def dispatch(graph_type, inputs):
        calls.append((graph_type, inputs))
        return json.dumps({"private": "private-fixture-key"})

    async def partial_sync(source, *, run_budget_seconds):
        assert source == "fixture" and run_budget_seconds == 0.001
        return {"outcome": "continued"}

    class Provider:
        closed = False

        async def get_summary(self, external_id):
            assert external_id == summary.external_id
            return summary

        async def aclose(self):
            self.closed = True

    provider = Provider()
    monkeypatch.setattr(runtime, "dispatch", dispatch)
    monkeypatch.setattr(factory, "build_meeting_provider", lambda config: provider)
    monkeypatch.setattr(service, "sync_source", partial_sync)
    monkeypatch.setattr(db, "list_summaries", lambda **kwargs: {"items": [row], "total": 1})
    monkeypatch.setattr(db, "get_summary", lambda summary_id: row)
    monkeypatch.setattr(db, "source_status", lambda source: [{"scan_started_at": None if calls else "checkpoint", "last_completed_at": "completed" if calls else None}])
    result = await meetings.verify_live("fixture", stage)
    assert calls == [("meeting_ingest", {"source": "fixture"})] * 2
    assert provider.closed
    assert result["normalized_summary_verified"] and result["replay_verified"]
    if stage == "scan":
        assert result["bounded_resume_verified"]
    if stage == "context":
        assert result["context_reader_verified"]
    rendered = json.dumps(result)
    assert all(value not in rendered for value in ("Private meeting", "private-fixture-key", "sensitive", "fixture-note"))

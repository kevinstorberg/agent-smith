import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from services.graphs.runtime import dispatch
from services.meetings import db, factory
from services.meetings.types import MeetingSummary, NotePage, NoteReference
from tests.conftest import clean_meeting_rows


@pytest.mark.asyncio
async def test_meeting_graph_persists_through_factory_and_replays(monkeypatch):
    account = "graph-" + uuid4().hex
    monkeypatch.setenv("MEETING_SOURCES_JSON", json.dumps({"graph-test": {
        "provider": "test", "account_key": account, "api_key_env": "MEETING_TEST_KEY",
    }}))
    monkeypatch.setenv("MEETING_TEST_KEY", "not-a-real-credential")
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    summary = MeetingSummary("test-note", "A meeting", "Agreed next step", None, "https://example.test/meeting", stamp, stamp)
    clients = []

    class Provider:
        closed = False

        def __init__(self, config):
            clients.append(self)

        async def list_page(self, cursor=None):
            return NotePage((NoteReference("test-note", stamp),))

        async def get_summary(self, external_id):
            return summary

        async def aclose(self):
            self.closed = True

    monkeypatch.setitem(factory._PROVIDER_BUILDERS, "test", Provider)
    try:
        first = json.loads(await dispatch("meeting_ingest", {"source": "graph-test"}))
        row = db.list_summaries(source="graph-test")["items"][0]
        second = json.loads(await dispatch("meeting_ingest", {"source": "graph-test"}))
        again = db.get_summary(row["id"])
        assert first["created"] == 1
        assert second["unchanged"] == 1
        assert again["id"] == row["id"]
        assert again["revision"] == row["revision"] == 1
        assert again["summary_text"] == summary.summary_text
        assert all(client.closed for client in clients)
        assert "Agreed next step" not in json.dumps(first)
    finally:
        clean_meeting_rows(account)

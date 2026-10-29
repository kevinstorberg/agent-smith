import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from services.db import get_connection
from services.graphs.runtime import dispatch
from services.meetings import factory
from services.meetings.types import NotePage
from tests.test_meeting_memory_flow import agents as agents, feed as feed
from tests.test_meeting_profile_flow import people as people, profiler as profiler
from tests.test_meeting_sync import source as source


@pytest.mark.asyncio
async def test_incremental_polls_do_not_repeat_completed_transcripts_or_agents(source, people, agents, profiler, monkeypatch):
    original = people.summaries["one"]
    people.summaries["one"] = replace(original, provider_updated_at=datetime.now(timezone.utc) - timedelta(seconds=30))
    builder = factory._PROVIDER_BUILDERS["test"]
    cutoffs, summary_calls, transcript_calls = [], [], []

    class MeteredProvider(builder):
        async def list_page(self, cursor=None, *, updated_after=None):
            cutoffs.append(updated_after)
            result = await super().list_page(cursor, updated_after=updated_after)
            return NotePage(tuple(item for item in result.notes if updated_after is None or item.updated_at > updated_after), result.next_cursor)

        async def get_summary(self, external_id):
            summary_calls.append(external_id)
            return await super().get_summary(external_id)

        async def get_transcript_page(self, external_id, cursor=None):
            transcript_calls.append(external_id)
            return await super().get_transcript_page(external_id, cursor)

    monkeypatch.setitem(factory._PROVIDER_BUILDERS, "test", MeteredProvider)
    await dispatch("meeting_ingest", {"source": source.name})
    initial_summary_calls = len(summary_calls)
    initial_transcript_calls = len(transcript_calls)
    assert initial_summary_calls > 0 and initial_transcript_calls == 1
    assert len(agents.analyses) == len(profiler[0]) == 1
    assert cutoffs == [None]

    for _ in range(2):
        overlap = json.loads(await dispatch("meeting_ingest", {"source": source.name}))
        assert overlap["unchanged"] == 1
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE meeting_sync_state SET last_pull_started_at = clock_timestamp() - interval '25 hours', last_deep_completed_at = clock_timestamp() - interval '25 hours' WHERE account_key = %s", (source.account_key,))
    await dispatch("meeting_ingest", {"source": source.name})
    assert len(summary_calls) == initial_summary_calls
    assert len(transcript_calls) == initial_transcript_calls

    changed_at = datetime.now(timezone.utc)
    people.summaries["one"] = replace(original, summary_text="An updated source summary", provider_updated_at=changed_at)
    await dispatch("meeting_ingest", {"source": source.name})
    assert len(summary_calls) == initial_summary_calls + 1
    assert len(transcript_calls) == initial_transcript_calls

    people.summaries = {}
    await dispatch("meeting_ingest", {"source": source.name})
    assert len(agents.analyses) == len(agents.publications) == len(profiler[0]) == 1
    assert all(cutoff is not None for cutoff in cutoffs[1:])

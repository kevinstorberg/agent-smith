from datetime import datetime, timedelta, timezone

import pytest

from services.db import get_connection
from services.jobs.models.job import set_schedule_enabled
from services.jobs.scheduler import JobScheduler
from services.jobs.service import has_requested_work
from services.meetings import digestion_db, manual_analysis, memory_db, profile_db
from services.personas import assessment_db
from tests.test_manual_analysis import jobs as jobs, payload as payload, saved as saved
from tests.test_meeting_sync import source as source


@pytest.fixture(autouse=True)
def deferred_assessments():
    # Assessment refresh has its own scheduler wake-up path, independent of meeting requests.
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, assessment_next_attempt_at FROM participant_profiles")
        previous = cur.fetchall()
        cur.execute("UPDATE participant_profiles SET assessment_next_attempt_at=clock_timestamp()+interval '1 day'")
    assert not assessment_db.has_requested_work()
    yield
    if previous:
        with get_connection() as conn, conn.cursor() as cur:
            cur.executemany("UPDATE participant_profiles SET assessment_next_attempt_at=%s WHERE id=%s",
                            [(next_attempt, key) for key, next_attempt in previous])


@pytest.fixture
def scheduled_graphs(source, jobs, monkeypatch):
    graphs = {kind: jobs(kind) for kind in ("meeting_ingest", "persona")}
    assert all(job["state"] == "active" and job["schedule_enabled"] for job in graphs.values())
    scheduler = JobScheduler()
    eligible = scheduler._eligible_jobs()
    assert {job["id"] for job in graphs.values()} <= {job["id"] for job in eligible}
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    scheduler._next_run.update({job["id"]: future for job in eligible})
    dispatched = []
    monkeypatch.setattr(scheduler, "_dispatch", lambda job: dispatched.append(job["input_params"]["graph_type"]))
    return scheduler, graphs, dispatched


def requested_graphs(graphs):
    return {kind for kind, job in graphs.items() if has_requested_work(job)}


def prepare_retry(meeting_id, stage):
    other = "profile" if stage == "memory" else "memory"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(f"""UPDATE meeting_digestions SET {stage}_status='failed', {stage}_attempts=3,
            {stage}_error='ModelCallTimeoutError', {other}_status='pending',
            {other}_next_attempt_at=clock_timestamp() WHERE meeting_id=%s""", (meeting_id,))


def request_profile(meeting_id, operation, payload):
    if operation == "retry":
        prepare_retry(meeting_id, "profile")
        profile_db.retry_profiles(meeting_id)
    else:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE meeting_digestions SET memory_status='pending' WHERE meeting_id=%s", (meeting_id,))
        manual_analysis.request_analysis(payload(meeting_id, scope="profiles"))


@pytest.mark.asyncio
async def test_analysis_cost_isolation_memory_retry_only_wakes_meeting_job(saved, scheduled_graphs):
    scheduler, graphs, dispatched = scheduled_graphs
    meeting_id = saved()
    prepare_retry(meeting_id, "memory")
    assert requested_graphs(graphs) == set()

    memory_db.retry_memories(meeting_id)

    assert digestion_db.get_record(meeting_id)["profile_status"] == "pending"
    assert requested_graphs(graphs) == {"meeting_ingest"}
    await scheduler._tick()
    assert dispatched == ["meeting_ingest"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["retry", "manual"])
async def test_analysis_cost_isolation_profile_request_only_wakes_persona(saved, payload, scheduled_graphs, operation):
    scheduler, graphs, dispatched = scheduled_graphs
    meeting_id = saved()
    assert requested_graphs(graphs) == set()

    request_profile(meeting_id, operation, payload)

    assert digestion_db.get_record(meeting_id)["memory_status"] == "pending"
    assert requested_graphs(graphs) == {"persona"}
    await scheduler._tick()
    assert dispatched == ["persona"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["retry", "manual"])
async def test_analysis_cost_isolation_paused_persona_never_dispatches_requested_work(saved, payload, scheduled_graphs, operation):
    scheduler, graphs, dispatched = scheduled_graphs
    set_schedule_enabled(graphs["persona"]["id"], False)
    meeting_id = saved()
    request_profile(meeting_id, operation, payload)

    assert requested_graphs(graphs) == {"persona"}
    assert graphs["persona"]["id"] not in {job["id"] for job in scheduler._eligible_jobs()}
    await scheduler._tick()
    assert dispatched == []


def test_analysis_cost_isolation_profile_claim_ignores_older_memory_request(source, saved):
    older_memory, requested_profile = saved(), saved()
    prepare_retry(older_memory, "memory")
    memory_db.retry_memories(older_memory)
    prepare_retry(requested_profile, "profile")
    profile_db.retry_profiles(requested_profile)
    owner = "cost-isolation-profile-priority"
    try:
        claimed = digestion_db.claim_profile(source.name, owner)
        assert claimed["meeting_id"] == requested_profile
        assert digestion_db.get_record(older_memory)["profile_claim_owner"] is None
    finally:
        digestion_db.release_profile_owner(owner)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "done"])
async def test_analysis_cost_isolation_legacy_shared_request_neither_wakes_nor_backfills(saved, scheduled_graphs, status):
    scheduler, graphs, dispatched = scheduled_graphs
    meeting_id = saved()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""UPDATE meeting_digestions SET requested_at=clock_timestamp()-interval '1 day',
            memory_status=%s, profile_status=%s WHERE meeting_id=%s""", (status, status, meeting_id))
    before = digestion_db.get_record(meeting_id)

    assert requested_graphs(graphs) == set()
    await scheduler._tick()

    assert dispatched == []
    assert digestion_db.get_record(meeting_id) == before


@pytest.mark.asyncio
async def test_analysis_cost_isolation_assessment_wake_remains_independent(scheduled_graphs):
    scheduler, graphs, dispatched = scheduled_graphs
    assert requested_graphs(graphs) == set()
    person = profile_db.create_profile("Independent assessment wake")
    try:
        assessment_db.request(person["id"], person["revision"])
        assert assessment_db.has_requested_work(person["id"])
        assert requested_graphs(graphs) == {"persona"}
        await scheduler._tick()
        assert dispatched == ["persona"]
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM participant_profiles WHERE id=%s", (person["id"],))

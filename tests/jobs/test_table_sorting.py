from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import psycopg2
from psycopg2 import sql
import pytest

from services.api.models import base
from services.api.routers.jobs import router
from services.db import get_connection
from services.jobs.models.job import list_jobs


@pytest.fixture
def jobs():
    marker = "job-sort-" + uuid4().hex
    names = ["Zulu", "alpha", "ALPHA", "charlie", "bravo", "delta"]
    ids = []
    with get_connection() as conn, conn.cursor() as cur:
        for index, name in enumerate([*names, "Proposed", "Rejected"]):
            cur.execute(
                """INSERT INTO background_jobs
                (name,description,schedule_config,input_params,schedule_enabled,
                 state,created_at,updated_at)
                VALUES(%s,'Unchanged description','{"hours":1}'::jsonb,
                 '{"command":"never execute this fixture"}'::jsonb,%s,%s,%s,%s)
                RETURNING id""",
                (marker + name, index in (0, 2, 3),
                 'active' if index < 6 else 'proposed' if index == 6 else 'rejected',
                 datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=[4, 1, 3, 2, 1, 4, 9, 9][index]),
                 datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=[1, 3, 2, 2, 1, 4, 9, 9][index])),
            )
            ids.append(cur.fetchone()[0])
    try:
        yield marker, ids
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM background_jobs WHERE id=ANY(%s)", (ids,))


ORDERS = [
    ('name', [1, 2, 4, 3, 5, 0]),
    ('name_desc', [0, 5, 3, 4, 2, 1]),
    ('updated_asc', [0, 4, 2, 3, 1, 5]),
    ('updated', [5, 1, 3, 2, 4, 0]),
    ('newest', [5, 0, 2, 3, 4, 1]),
]


@pytest.mark.parametrize('sort,positions', ORDERS)
def test_job_sort_is_global_before_page_and_preserves_state_versions_and_execution_ledger(jobs, sort, positions):
    marker, ids = jobs
    app = FastAPI()
    app.include_router(router, prefix='/jobs')
    client = TestClient(app)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute('SELECT * FROM background_jobs WHERE id=ANY(%s) ORDER BY id', (ids,))
        before = cur.fetchall()
    pages = [client.get('/jobs', params={'q': marker, 'sort': sort, 'limit': 2, 'offset': offset}) for offset in (0, 2, 4)]
    assert all(page.status_code == 200 for page in pages), [page.text for page in pages]
    assert [row['id'] for page in pages for row in page.json()['items']] == [ids[i] for i in positions]
    assert [page.json()['total'] for page in pages] == [6, 6, 6]
    assert list_jobs(q=marker, sort=sort, limit=2, offset=99) == ([], 6)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute('SELECT * FROM background_jobs WHERE id=ANY(%s) ORDER BY id', (ids,))
        assert cur.fetchall() == before
        cur.execute('SELECT COUNT(*) FROM job_executions WHERE job_id=ANY(%s)', (ids,))
        assert cur.fetchone()[0] == 0


def test_job_sort_preserves_search_and_scheduling_filter(jobs):
    marker, ids = jobs
    rows, total = list_jobs(q=marker, schedule_enabled=True, sort='name_desc', limit=1, offset=1)
    assert total == 3 and [row['id'] for row in rows] == [ids[3]]


def test_job_non_ascii_text_uses_native_postgres_case_folding_and_stable_ties(jobs):
    marker, ids = jobs
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute('UPDATE background_jobs SET name=%s WHERE id=%s', (marker+'éAlpha', ids[0]))
        cur.execute('UPDATE background_jobs SET name=%s WHERE id=%s', (marker+'éALPHA', ids[1]))
    rows, total = list_jobs(q=marker, sort='name_desc')
    assert total == 6 and [row['id'] for row in rows[:2]] == [ids[1], ids[0]]


@pytest.mark.parametrize('field', ['name', 'updated_at'])
def test_visible_job_sort_fields_have_a_nonnull_database_contract(jobs, field):
    _, ids = jobs
    with pytest.raises(psycopg2.errors.NotNullViolation), get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL('UPDATE background_jobs SET {}=NULL WHERE id=%s').format(sql.Identifier(field)), (ids[0],))


@pytest.mark.parametrize('sort', ['name ASC', 'schedule', '', 'updated_asc;DROP TABLE background_jobs'])
def test_job_sort_rejects_unknown_keys_before_sql(monkeypatch, sort):
    app = FastAPI()
    app.include_router(router, prefix='/jobs')
    assert TestClient(app).get('/jobs', params={'sort': sort}).status_code == 422
    monkeypatch.setattr(base, 'get_connection', lambda: pytest.fail('Invalid sort reached SQL'))
    with pytest.raises(ValueError, match='Sort must be one of'):
        list_jobs(sort=sort)

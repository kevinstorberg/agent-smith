from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from threading import Event
import time

import pytest
from psycopg2.extras import Json

from services.api.models.shared import harness, harness_ordering
from services.api.models.shared.harness import get_item, get_item_by_id, harness_write, list_items_summary
from services.db import get_connection
from services.proposals import service
from tests.test_harness_ordering import CONTENT, client as client, isolated_harness_order as isolated_harness_order, item, order, payload


def proposal(source):
    row = get_item_by_id('rule', source)
    return service.persist_proposal(service.stage_proposal({
        'target_kind': 'rule', 'action': 'update', 'target_name': row['name'],
        'title': 'Retain current ordering', 'rationale': 'Synthetic concurrent ordering regression',
        'body': 'Updated synthetic body', 'evidence': [{'source': 'plan', 'id': '12', 'note': 'Synthetic ordering fixture'}],
    }))


def watch_writer(monkeypatch):
    entered = Event()
    backend = []

    @contextmanager
    def watched_connection():
        with get_connection() as conn:
            backend.append(conn.get_backend_pid())
            entered.set()
            yield conn

    monkeypatch.setattr(harness, 'get_connection', watched_connection)
    monkeypatch.setattr(service, 'get_connection', watched_connection)
    return entered, backend


def wait_for_block(connection, future, backend):
    deadline = time.monotonic() + 2
    while True:
        with connection.cursor() as cur:
            cur.execute('SELECT pg_blocking_pids(%s)', (backend,))
            blockers = cur.fetchone()[0]
        if connection.get_backend_pid() in blockers:
            return
        if future.done():
            future.result()
            pytest.fail('writer bypassed the shared kind lock')
        assert time.monotonic() < deadline, f'writer did not wait on the shared kind lock: {blockers}'
        time.sleep(0.01)


@pytest.mark.parametrize('writer', ['create', 'content', 'upsert', 'metadata', 'delete', 'bulk', 'approval'])
def test_runtime_writers_wait_on_the_kind_lock_before_writing(monkeypatch, writer):
    source, anchor = item('rule', 'source', 10), item('rule', 'anchor', 20)
    proposal_id = proposal(source) if writer == 'approval' else None
    operations = {
        'create': lambda: item('rule', 'new', 30),
        'content': lambda: harness.update_content('rule', source, {'body': 'New content'}),
        'upsert': lambda: harness.upsert_item('rule', 'ord_source', {'body': 'Upserted content'}),
        'metadata': lambda: harness.update_metadata('rule', source, clone_as_skill=True),
        'delete': lambda: harness.delete_item('rule', source),
        'bulk': lambda: harness.reorder_items('rule', [anchor, source]),
        'approval': lambda: service.promote_proposal(proposal_id),
    }
    with ThreadPoolExecutor(max_workers=1) as executor:
        with harness_write('rule') as blocker:
            entered, backend = watch_writer(monkeypatch)
            future = executor.submit(operations[writer])
            assert entered.wait(2), 'writer did not acquire a connection'
            wait_for_block(blocker, future, backend[0])
        future.result(timeout=5)


def test_another_kind_is_not_blocked_by_an_unrelated_kind_lock():
    with ThreadPoolExecutor(max_workers=1) as executor, harness_write('rule'):
        result = executor.submit(item, 'skill', 'independent', 10).result(timeout=2)
        assert get_item_by_id('skill', result)['name'] == 'ord_independent'


def test_move_lock_contention_is_a_bounded_http_conflict_and_releases_cleanly(client):
    source, anchor = item('rule', 'source', 10), item('rule', 'anchor', 20)
    request = payload('rule', source, anchor)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with harness_write('rule'):
            started = time.monotonic()
            response = executor.submit(client.post, f'/harness/items/rule/{source}/move', json=request).result(timeout=6)
            assert response.status_code == 409 and 'busy' in response.json()['detail']
            assert time.monotonic() - started < 6
        assert client.post(f'/harness/items/rule/{source}/move', json=request).status_code == 200


@pytest.mark.parametrize('path', ['content', 'metadata'])
def test_existing_base_and_overridden_write_routes_map_lock_conflicts_consistently(client, path):
    source = item('rule', 'source', 10)
    before = get_item_by_id('rule', source)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with harness_write('rule'):
            if path == 'content':
                waiting = executor.submit(client.put, f'/harness/items/rule/{source}/content', json={'content': CONTENT})
            else:
                waiting = executor.submit(client.patch, f'/harness/items/rule/{source}', json={'enabled': False})
            response = waiting.result(timeout=6)
            assert response.status_code == 409 and 'busy' in response.json()['detail']
    assert get_item_by_id('rule', source) == before


@pytest.mark.parametrize('path', ['content', 'upsert', 'approval'])
def test_new_versions_preserve_the_current_position_after_a_move(client, path):
    source = item('rule', 'source', 10)
    item('rule', 'hidden', 20)
    anchor = item('rule', 'anchor', 30)
    proposal_id = proposal(source) if path == 'approval' else None
    assert client.post(f'/harness/items/rule/{source}/move', json=payload('rule', source, anchor)).status_code == 200
    before = [row['name'] for row in list_items_summary('rule')]
    position = get_item_by_id('rule', source)['sort_key']
    if path == 'content':
        new_id = harness.update_content('rule', source, {'body': 'Content after move'})
    elif path == 'upsert':
        new_id = harness.upsert_item('rule', 'ord_source', {'body': 'Upsert after move'})
    else:
        new_id = service.promote_proposal(proposal_id)['applied_ref']['item_id']
    assert new_id != source
    assert get_item_by_id('rule', new_id)['sort_key'] == position
    assert [row['name'] for row in list_items_summary('rule')] == before


def test_explicit_upsert_position_remains_an_intentional_override():
    item('rule', 'source', 20)
    new_id = harness.upsert_item('rule', 'ord_source', {'body': 'Explicit order'}, sort_key=7)
    assert get_item_by_id('rule', new_id)['sort_key'] == 7


def test_content_version_waits_for_an_actual_move_and_copies_its_committed_position(monkeypatch):
    source = item('rule', 'source', 10)
    item('rule', 'hidden', 20)
    anchor = item('rule', 'anchor', 30)
    request = payload('rule', source, anchor)
    request['expected_updated_at'] = datetime.fromisoformat(request['expected_updated_at'])
    request['expected_anchor_updated_at'] = datetime.fromisoformat(request['expected_anchor_updated_at'])
    move_ready, finish_move = Event(), Event()
    original = harness_ordering._latest_order
    paused = False

    def pause_locked_move(cursor, table):
        nonlocal paused
        result = original(cursor, table)
        if not paused:
            paused = True
            move_ready.set()
            assert finish_move.wait(5), 'test did not release its owned move'
        return result

    monkeypatch.setattr(harness_ordering, '_latest_order', pause_locked_move)
    with ThreadPoolExecutor(max_workers=2) as executor:
        moving = executor.submit(harness_ordering.move_item, 'rule', source, **request)
        assert move_ready.wait(2)
        entered, backend = watch_writer(monkeypatch)
        versioning = executor.submit(harness.update_content, 'rule', source, {'body': 'Version after move'})
        try:
            assert entered.wait(2)
            with get_connection() as observer, observer.cursor() as cur:
                deadline = time.monotonic() + 2
                while True:
                    cur.execute('SELECT pg_blocking_pids(%s)', (backend[0],))
                    if cur.fetchone()[0]:
                        break
                    assert not versioning.done(), 'version bypassed the active move transaction'
                    assert time.monotonic() < deadline, 'version did not wait on the active move transaction'
                    time.sleep(0.01)
        finally:
            finish_move.set()
        moved = moving.result(timeout=5)
        new_id = versioning.result(timeout=5)
    assert get_item_by_id('rule', new_id)['sort_key'] == moved['sort_key']
    assert order('rule')[-1] == new_id
    assert get_item('rule', 'ord_source')['id'] == new_id


def test_borrowed_write_context_never_commits_the_callers_transaction():
    source = item('rule', 'source', 10)
    before = get_item_by_id('rule', source)
    with pytest.raises(RuntimeError, match='owned rollback'):
        with get_connection() as conn:
            with harness_write('rule', conn=conn), conn.cursor() as cur:
                cur.execute('UPDATE harness_rules SET sort_key=999 WHERE id=%s', (source,))
            raise RuntimeError('owned rollback')
    assert get_item_by_id('rule', source) == before
    with harness_write('rule'):
        pass


def test_noop_validates_tokens_without_changing_positions_or_timestamps(client):
    source, anchor = item('rule', 'source', 10), item('rule', 'anchor', 20)
    before = list_items_summary('rule')
    assert client.post(f'/harness/items/rule/{source}/move', json=payload('rule', source, anchor, after=False)).status_code == 200
    assert list_items_summary('rule') == before


def test_owned_large_tied_kind_retains_every_hidden_relative_order(client):
    with harness_write('rule') as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO harness_rules(name,agents,subagents,content,sort_key,version)
            SELECT 'ord_stress_'||value, ARRAY['claude'], ARRAY[]::text[], %s, 0, 1
            FROM generate_series(1,500) AS value RETURNING id""", (Json(CONTENT),))
        rows = [row[0] for row in cur.fetchall()]
    before = order('rule')
    assert client.post(f'/harness/items/rule/{rows[0]}/move', json=payload('rule', rows[0], rows[-1])).status_code == 200
    after = order('rule')
    assert set(after) == set(before)
    assert [value for value in after if value != rows[0]] == [value for value in before if value != rows[0]]
    assert after[-1] == rows[0]

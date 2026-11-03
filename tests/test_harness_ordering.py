from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from psycopg2.extras import Json

from services.api.models.shared.harness import (
    VALID_TABLES, create_item, get_item_by_id, list_items_summary, update_content, update_metadata,
)
from services.api.routers import harness_router
from services.db import get_connection


CONTENT = {"body": "Synthetic ordering fixture", "metadata": {}}


@pytest.fixture(autouse=True)
def isolated_harness_order():
    saved = {}
    with get_connection() as conn, conn.cursor() as cur:
        for kind, table in VALID_TABLES.items():
            cur.execute(f"SELECT id, sort_key, updated_at FROM {table}")
            saved[kind] = cur.fetchall()
    yield
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM improvement_proposals WHERE target_name LIKE 'ord_%'")
        for kind, table in VALID_TABLES.items():
            cur.execute(f"DELETE FROM harness_configs WHERE item_type=%s AND item_id IN (SELECT id FROM {table} WHERE name LIKE %s)", (kind, 'ord_%'))
            cur.execute(f"DELETE FROM {table} WHERE name LIKE 'ord_%'")
            if saved[kind]:
                cur.execute(
                    f"""UPDATE {table} AS item SET sort_key=saved.position, updated_at=saved.stamp
                    FROM unnest(%s::int[],%s::int[],%s::timestamptz[]) AS saved(id,position,stamp)
                    WHERE item.id=saved.id""",
                    tuple(list(values) for values in zip(*saved[kind])),
                )


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(harness_router, prefix="/harness")
    return TestClient(app)


def item(kind, name, position, *, project=None, agents=None):
    return create_item(kind, 'ord_' + name, CONTENT, sort_key=position, project=project, agents=agents or ['claude'])


def order(kind):
    return [row['id'] for row in list_items_summary(kind)]


def payload(kind, source, anchor, *, after=True):
    return {
        'expected_updated_at': get_item_by_id(kind, source)['updated_at'].isoformat(),
        'expected_anchor_updated_at': get_item_by_id(kind, anchor)['updated_at'].isoformat(),
        'after_id' if after else 'before_id': anchor,
    }


@pytest.mark.parametrize('kind', list(VALID_TABLES))
def test_filtered_move_preserves_hidden_latest_rows_and_real_http_timestamp_tokens(client, kind):
    rows = [item(kind, str(index), index + 10, project='target' if index % 2 == 0 else 'hidden',
                 agents=['claude'] if index % 2 == 0 else ['codex']) for index in range(5)]
    before = order(kind)
    visible = client.get(f'/harness/items/{kind}', params={'project': 'target', 'agent': 'claude', 'name': 'ord_'}).json()['items']
    assert [row['id'] for row in visible] == rows[::2]
    response = client.post(f'/harness/items/{kind}/{rows[0]}/move', json={
        'expected_updated_at': visible[0]['updated_at'], 'expected_anchor_updated_at': visible[-1]['updated_at'], 'after_id': rows[-1],
    })
    assert response.status_code == 200, response.text
    after = order(kind)
    assert after == [value for value in before if value != rows[0]] + [rows[0]]
    assert [value for value in after if value != rows[0]] == [value for value in before if value != rows[0]]
    assert get_item_by_id(kind, rows[0])['content'] == CONTENT


def test_page_edge_move_anchors_after_visible_neighbor_before_hidden_tail(client):
    rows = [item('rule', str(index), index + 10, agents=['claude'] if index % 2 == 0 else ['codex']) for index in range(9)]
    page = client.get('/harness/items/rule', params={'agent': 'claude', 'name': 'ord_', 'offset': 2, 'limit': 2}).json()
    assert [row['id'] for row in page['items']] == [rows[4], rows[6]]
    before = order('rule')
    response = client.post(f'/harness/items/rule/{rows[4]}/move', json=payload('rule', rows[4], rows[6]))
    assert response.status_code == 200
    expected = [value for value in before if value != rows[4]]
    expected.insert(expected.index(rows[6]) + 1, rows[4])
    assert order('rule') == expected
    assert order('rule')[-2:] == rows[-2:]


def test_tied_positions_use_id_order_and_historical_rows_are_untouched(client):
    old = item('rule', 'history', 10)
    source = update_content('rule', old, {'body': 'Current version'})
    anchor = item('rule', 'anchor', 10)
    hidden = item('rule', 'hidden', 10)
    before = order('rule')
    response = client.post(f'/harness/items/rule/{hidden}/move', json=payload('rule', hidden, source, after=False))
    assert response.status_code == 200
    expected = [value for value in before if value != hidden]
    expected.insert(expected.index(source), hidden)
    assert order('rule') == expected
    assert get_item_by_id('rule', old)['sort_key'] == 10
    assert source in order('rule') and anchor in order('rule') and old not in order('rule')


@pytest.mark.parametrize('changed', ['source', 'anchor'])
def test_stale_metadata_or_replaced_version_conflicts_without_writes(client, changed):
    source, anchor = item('rule', 'source', 10), item('rule', 'anchor', 20)
    request = payload('rule', source, anchor)
    update_metadata('rule', source if changed == 'source' else anchor, enabled=False)
    before = order('rule')
    response = client.post(f'/harness/items/rule/{source}/move', json=request)
    assert response.status_code == 409
    assert order('rule') == before
    current_request = payload('rule', source, anchor)
    update_content('rule', source if changed == 'source' else anchor, {'body': 'New version'})
    before = order('rule')
    response = client.post(f'/harness/items/rule/{source}/move', json=current_request)
    assert response.status_code == 409
    assert order('rule') == before


def test_microsecond_tokens_round_trip_and_timezone_offsets_compare_exactly(client):
    source, anchor = item('rule', 'source', 10), item('rule', 'anchor', 20)
    stamp = datetime(2026, 11, 3, 12, 0, 0, 123456, tzinfo=timezone.utc)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute('UPDATE harness_rules SET updated_at=%s WHERE id=ANY(%s)', (stamp, [source, anchor]))
    row = client.get(f'/harness/items/rule/{source}').json()
    assert '.123456' in row['updated_at']
    request = payload('rule', source, anchor)
    request['expected_anchor_updated_at'] = '2026-11-03T17:00:00.123456+05:00'
    response = client.post(f'/harness/items/rule/{source}/move', json=request)
    assert response.status_code == 200


@pytest.mark.parametrize('mutation', [
    {'after_id': True}, {'after_id': -1}, {'before_id': 2}, {'after_id': None},
    {'unknown': 1}, {'expected_updated_at': '2026-11-03T12:00:00'},
])
def test_invalid_move_contract_is_rejected(client, mutation):
    source, anchor = item('rule', 'source', 10), item('rule', 'anchor', 20)
    request = {**payload('rule', source, anchor), **mutation}
    response = client.post(f'/harness/items/rule/{source}/move', json=request)
    assert response.status_code == 422


def test_proposed_and_self_anchors_are_not_eligible(client):
    source = item('rule', 'source', 10)
    response = client.post(f'/harness/items/rule/{source}/move', json=payload('rule', source, source))
    assert response.status_code == 422
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO harness_rules(name,agents,subagents,content,sort_key,version,state) VALUES('ord_proposed','{}','{}',%s,0,NULL,'proposed') RETURNING id", (Json(CONTENT),))
        proposed = cur.fetchone()[0]
    response = client.post(f'/harness/items/rule/{source}/move', json=payload('rule', source, proposed))
    assert response.status_code == 409


def test_failed_postcondition_rolls_back_every_position_and_timestamp(client, monkeypatch):
    from services.api.models.shared import harness_ordering

    source, anchor = item('rule', 'source', 10), item('rule', 'anchor', 20)
    before = list_items_summary('rule')
    original = harness_ordering._latest_order
    captured = []

    def changed_postcondition(cursor, table):
        rows = original(cursor, table)
        if not captured:
            captured.extend(rows)
            return rows
        return captured

    monkeypatch.setattr(harness_ordering, '_latest_order', changed_postcondition)
    with pytest.raises(RuntimeError, match='complete order'):
        client.post(f'/harness/items/rule/{source}/move', json=payload('rule', source, anchor))
    assert list_items_summary('rule') == before


@pytest.mark.parametrize('deleted', ['source', 'anchor'])
def test_deleted_source_or_anchor_is_rejected_without_reordering(client, deleted):
    from services.api.models.shared.harness import delete_item

    source, anchor = item('rule', 'source', 10), item('rule', 'anchor', 20)
    request = payload('rule', source, anchor)
    delete_item('rule', source if deleted == 'source' else anchor)
    before = list_items_summary('rule')
    assert client.post(f'/harness/items/rule/{source}/move', json=request).status_code == 409
    assert list_items_summary('rule') == before

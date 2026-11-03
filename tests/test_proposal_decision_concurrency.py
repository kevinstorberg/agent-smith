from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from queue import Queue
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2.errors import DeadlockDetected
import pytest

from services.api.models.proposal import get_proposal
from services.api.models.shared.harness import create_item, get_item, get_item_by_id
from services.api.routers.proposals import router
from services.db import get_connection
from services.jobs.models import job as job_model
from services.jobs.models.job import get_job
from services.jobs.service import create_job_with_default_config
from services.proposals import service
from tests.conftest import harness_cleanup, jobs_cleanup


_clean_harness = harness_cleanup('pdec_%')
_clean_jobs = jobs_cleanup('pdec_%')


@pytest.fixture(autouse=True)
def clean_proposals():
    yield
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM improvement_proposals WHERE target_name LIKE 'pdec_%'")


@pytest.fixture(params=['rule', 'job'])
def pending(request):
    kind = request.param
    name = 'pdec_' + kind
    if kind == 'rule':
        target_id = create_item('rule', name, {'body': 'Original synthetic content'}, agents=['claude'])
        change = {'body': 'Approved synthetic content'}
    else:
        target_id = create_job_with_default_config(name, {'hours': 1}, {'command': 'echo inert-fixture'})
        change = {'schedule_config': {'hours': 2}}
    proposal_id = service.persist_proposal(service.stage_proposal({
        'target_kind': kind, 'action': 'update', 'target_name': name, 'title': 'Synthetic decision',
        'rationale': 'Exercise native proposal decision ordering', 'evidence': [], **change,
    }))
    return {'kind': kind, 'name': name, 'id': proposal_id, 'target_id': target_id,
            'proposed_id': get_proposal(proposal_id)['proposed_item_id']}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix='/proposals')
    with TestClient(app) as client:
        yield client


def watch_decision_connections(monkeypatch):
    connections = Queue()

    @contextmanager
    def watched_connection():
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout = '8s'")
            connections.put(conn.get_backend_pid())
            yield conn

    monkeypatch.setattr(service, 'get_connection', watched_connection)
    return connections


def wait_for_block(cursor, backend, future, owner=None):
    deadline = time.monotonic() + 2
    while True:
        cursor.execute('SELECT pg_blocking_pids(%s)', (backend,))
        blockers = cursor.fetchone()[0]
        blocked = owner in blockers if owner is not None else bool(blockers)
        if blocked:
            return
        if future.done():
            pytest.fail(f'decision completed before the owned lock was released: {future.result()}')
        assert time.monotonic() < deadline, f'decision never reached its expected lock: {blockers}'
        time.sleep(0.01)


def decide(action, proposal_id):
    try:
        return action(proposal_id)
    except Exception as error:
        return error


def race_with_held_master(monkeypatch, pending, first, second):
    connections = watch_decision_connections(monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as executor:
        with get_connection() as blocker, blocker.cursor() as cur:
            cur.execute('SELECT id FROM improvement_proposals WHERE id=%s FOR UPDATE', (pending['id'],))
            first_result = executor.submit(decide, first, pending['id'])
            wait_for_block(cur, connections.get(timeout=2), first_result, blocker.get_backend_pid())
            second_result = executor.submit(decide, second, pending['id'])
            wait_for_block(cur, connections.get(timeout=2), second_result)
        return first_result.result(timeout=8), second_result.result(timeout=8)


def test_reject_cannot_overwrite_an_approval_that_wins_the_master_lock(monkeypatch, pending):
    approved, rejected = race_with_held_master(monkeypatch, pending, service.promote_proposal, service.reject_proposal)
    assert isinstance(approved, dict) and approved['status'] == 'approved', approved
    assert isinstance(rejected, service.ProposalConflictError), rejected
    assert get_proposal(pending['id'])['status'] == 'approved'
    if pending['kind'] == 'rule':
        assert get_item('rule', pending['name'])['id'] == pending['proposed_id']
        assert get_item_by_id('rule', pending['proposed_id'])['state'] == 'active'
    else:
        assert get_job(pending['target_id'])['version'] == 2


def assert_original(pending):
    target = get_item('rule', pending['name']) if pending['kind'] == 'rule' else get_job(pending['target_id'])
    assert target['id'] == pending['target_id']
    assert target['version'] == 1


def assert_applied_once(pending):
    if pending['kind'] == 'rule':
        target = get_item('rule', pending['name'])
        assert target['id'] == pending['proposed_id']
        assert target['content']['body'] == 'Approved synthetic content'
        table, field, target_id = 'harness_configs', 'item_id', pending['proposed_id']
    else:
        target = get_job(pending['target_id'])
        assert target['schedule_config'] == {'hours': 2}
        assert get_job(pending['proposed_id']) is None
        table, field, target_id = 'job_configs', 'job_id', pending['target_id']
    assert target['state'] == 'active' and target['version'] == 2
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(f'SELECT count(*) FROM {table} WHERE {field}=%s', (target_id,))
        assert cur.fetchone()[0] == 1


def test_approval_cannot_reverse_a_rejection_that_wins_the_master_lock(monkeypatch, pending):
    rejected, approved = race_with_held_master(monkeypatch, pending, service.reject_proposal, service.promote_proposal)
    assert isinstance(rejected, dict) and rejected['status'] == 'rejected', rejected
    assert isinstance(approved, service.ProposalConflictError), approved
    assert get_proposal(pending['id'])['status'] == 'rejected'
    assert_original(pending)


def test_double_approval_applies_content_and_configs_once(monkeypatch, pending):
    first, second = race_with_held_master(monkeypatch, pending, service.promote_proposal, service.promote_proposal)
    assert isinstance(first, dict) and first['status'] == 'approved', first
    assert isinstance(second, service.ProposalConflictError), second
    assert_applied_once(pending)


@pytest.mark.parametrize('decision', [service.promote_proposal, service.reject_proposal, service.delete_proposal])
def test_delete_winner_removes_pending_content_and_loser_reports_missing(monkeypatch, pending, decision):
    deleted, later = race_with_held_master(monkeypatch, pending, service.delete_proposal, decision)
    assert deleted is None, deleted
    assert isinstance(later, service.ProposalNotFoundError), later
    assert get_proposal(pending['id']) is None
    proposed = get_item_by_id('rule', pending['proposed_id']) if pending['kind'] == 'rule' else get_job(pending['proposed_id'])
    assert proposed is None
    assert_original(pending)


def test_deleting_approved_audit_record_preserves_live_content(monkeypatch, pending):
    approved, deleted = race_with_held_master(monkeypatch, pending, service.promote_proposal, service.delete_proposal)
    assert isinstance(approved, dict) and approved['status'] == 'approved', approved
    assert approved['applied_ref']
    assert deleted is None, deleted
    assert get_proposal(pending['id']) is None
    assert_applied_once(pending)


def test_deleting_rejected_audit_record_removes_rejected_content(monkeypatch, pending):
    rejected, deleted = race_with_held_master(monkeypatch, pending, service.reject_proposal, service.delete_proposal)
    assert isinstance(rejected, dict) and rejected['status'] == 'rejected', rejected
    assert deleted is None, deleted
    assert get_proposal(pending['id']) is None
    assert_original(pending)


@pytest.mark.parametrize('failure', [RuntimeError, DeadlockDetected])
def test_failed_decision_rolls_back_content_configs_and_master(monkeypatch, pending, failure):
    record = service._record_decision

    def fail_after_record(*args, **kwargs):
        record(*args, **kwargs)
        raise failure('synthetic failure after content and master updates')

    with monkeypatch.context() as patch:
        patch.setattr(service, '_record_decision', fail_after_record)
        expected = service.ProposalConflictError if failure is DeadlockDetected else RuntimeError
        with pytest.raises(expected):
            service.promote_proposal(pending['id'])
    assert get_proposal(pending['id'])['status'] == 'pending'
    assert_original(pending)
    proposed = get_item_by_id('rule', pending['proposed_id']) if pending['kind'] == 'rule' else get_job(pending['proposed_id'])
    assert proposed['state'] == 'proposed'
    if pending['kind'] == 'rule':
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM harness_configs WHERE item_id=%s AND item_type=%s', (pending['proposed_id'], 'rule'))
            assert cur.fetchone()[0] == 0
    assert service.promote_proposal(pending['id'])['status'] == 'approved'
    assert_applied_once(pending)


def test_http_locked_master_is_bounded_conflict_without_partial_apply(monkeypatch, pending, client):
    connections = watch_decision_connections(monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with get_connection() as blocker, blocker.cursor() as cur:
            cur.execute('SELECT id FROM improvement_proposals WHERE id=%s FOR UPDATE', (pending['id'],))
            response = executor.submit(client.post, f"/proposals/{pending['id']}/approve")
            wait_for_block(cur, connections.get(timeout=2), response, blocker.get_backend_pid())
            result = response.result(timeout=7)
    assert result.status_code == 409, result.text
    assert 'busy' in result.json()['detail'].lower()
    assert get_proposal(pending['id'])['status'] == 'pending'
    assert_original(pending)
    assert client.post(f"/proposals/{pending['id']}/approve").status_code == 200


@pytest.mark.parametrize('action', ['approve', 'reject', 'delete'])
def test_http_decisions_report_missing_after_deletion(pending, client, action):
    service.delete_proposal(pending['id'])
    path = f"/proposals/{pending['id']}"
    response = client.delete(path) if action == 'delete' else client.post(path + '/' + action)
    assert response.status_code == 404


@pytest.mark.parametrize('pending', ['rule'], indirect=True)
def test_harness_decision_waits_for_kind_before_locking_master(monkeypatch, pending):
    connections = watch_decision_connections(monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with get_connection() as blocker, blocker.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended('agent-smith:harness-write:rule', 0))")
            approved = executor.submit(service.promote_proposal, pending['id'])
            wait_for_block(cur, connections.get(timeout=2), approved, blocker.get_backend_pid())
            cur.execute('SELECT id FROM improvement_proposals WHERE id=%s FOR UPDATE NOWAIT', (pending['id'],))
            assert cur.fetchone()[0] == pending['id']
        assert approved.result(timeout=7)['status'] == 'approved'


@pytest.mark.parametrize('pending', ['job'], indirect=True)
@pytest.mark.parametrize('writer_commits', [False, True])
def test_job_decision_revalidates_after_an_ordinary_writer(monkeypatch, pending, writer_commits):
    connections = watch_decision_connections(monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with get_connection() as blocker, blocker.cursor() as cur:
            @contextmanager
            def borrowed_writer_connection():
                yield blocker

            with monkeypatch.context() as patch:
                patch.setattr(job_model, 'get_connection', borrowed_writer_connection)
                job_model.set_schedule_enabled(pending['target_id'], False)
            approved = executor.submit(decide, service.promote_proposal, pending['id'])
            wait_for_block(cur, connections.get(timeout=2), approved, blocker.get_backend_pid())
            if not writer_commits:
                assert isinstance(approved.result(timeout=7), service.ProposalConflictError)
                blocker.rollback()
        result = approved.result(timeout=7)
        assert isinstance(result, service.ProposalConflictError), result
    assert get_proposal(pending['id'])['status'] == 'pending'
    if writer_commits:
        assert 'changed' in str(result)
        assert get_job(pending['target_id'])['version'] == 2
        assert get_job(pending['target_id'])['schedule_enabled'] is False
        assert get_job(pending['proposed_id'])['state'] == 'proposed'
    else:
        assert_original(pending)
        assert service.promote_proposal(pending['id'])['status'] == 'approved'


@pytest.mark.parametrize('rollback', [False, True])
def test_local_timeouts_and_transaction_locks_do_not_leak(monkeypatch, pending, rollback):
    with get_connection() as conn:
        def settings():
            with conn.cursor() as cur:
                cur.execute("SELECT current_setting('lock_timeout'), current_setting('statement_timeout')")
                return cur.fetchone()

        original = settings()

        @contextmanager
        def reuse_connection():
            with conn:
                yield conn

        monkeypatch.setattr(service, 'get_connection', reuse_connection)
        if rollback:
            with pytest.raises(RuntimeError, match='intentional rollback'):
                with service._decision(pending['id']) as (cur, _):
                    assert settings() == ('3s', '5s')
                    raise RuntimeError('intentional rollback')
        else:
            assert service.reject_proposal(pending['id'])['status'] == 'rejected'
        assert settings() == original
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory'")
            assert cur.fetchone()[0] == 0


@pytest.mark.parametrize('decision', [service.promote_proposal, service.reject_proposal])
def test_committed_response_snapshot_survives_immediate_audit_deletion(monkeypatch, pending, decision):
    original = service._decision

    @contextmanager
    def delete_after_commit(*args, **kwargs):
        with original(*args, **kwargs) as locked:
            yield locked
        with monkeypatch.context() as patch:
            patch.setattr(service, '_decision', original)
            service.delete_proposal(pending['id'])

    monkeypatch.setattr(service, '_decision', delete_after_commit)
    result = decision(pending['id'])
    assert isinstance(result, dict) and result['status'] in {'approved', 'rejected'}
    assert result['updated_at'] and get_proposal(pending['id']) is None


@pytest.mark.parametrize('kind', ['rule', 'job'])
def test_deleting_approved_create_preserves_live_content_and_config(kind):
    name = 'pdec_created_' + kind
    change = {'body': 'New synthetic content'} if kind == 'rule' else {
        'schedule_config': {'hours': 2}, 'input_params': {'command': 'echo inert-fixture'},
    }
    proposal_id = service.persist_proposal(service.stage_proposal({
        'target_kind': kind, 'action': 'create', 'target_name': name, 'title': 'Create synthetic content',
        'rationale': 'Audit deletion must not delete an approved creation', 'evidence': [], **change,
    }))
    approved = service.promote_proposal(proposal_id)
    target_id = approved['proposed_item_id']
    service.delete_proposal(proposal_id)
    assert get_proposal(proposal_id) is None
    live = get_item_by_id(kind, target_id) if kind == 'rule' else get_job(target_id)
    assert live['state'] == 'active' and live['version'] == 1
    table, field = ('harness_configs', 'item_id') if kind == 'rule' else ('job_configs', 'job_id')
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(f'SELECT count(*) FROM {table} WHERE {field}=%s', (target_id,))
        assert cur.fetchone()[0] == 1


def test_distinct_proposals_for_one_live_target_cannot_both_apply(monkeypatch, pending):
    change = {'body': 'Second synthetic change'} if pending['kind'] == 'rule' else {'schedule_config': {'hours': 3}}
    second_id = service.persist_proposal(service.stage_proposal({
        'target_kind': pending['kind'], 'action': 'update', 'target_name': pending['name'],
        'title': 'Another proposal', 'rationale': 'Competing proposals share one live target', 'evidence': [], **change,
    }))
    connections = watch_decision_connections(monkeypatch)
    table = 'harness_rules' if pending['kind'] == 'rule' else 'background_jobs'
    with ThreadPoolExecutor(max_workers=2) as executor:
        with get_connection() as blocker, blocker.cursor() as cur:
            cur.execute(f'SELECT id FROM {table} WHERE id=%s FOR UPDATE', (pending['target_id'],))
            first = executor.submit(decide, service.promote_proposal, pending['id'])
            wait_for_block(cur, connections.get(timeout=2), first, blocker.get_backend_pid())
            second = executor.submit(decide, service.promote_proposal, second_id)
            wait_for_block(cur, connections.get(timeout=2), second)
        assert first.result(timeout=7)['status'] == 'approved'
        assert isinstance(second.result(timeout=7), service.ProposalConflictError)
    assert get_proposal(second_id)['status'] == 'pending'
    assert_applied_once(pending)

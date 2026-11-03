from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.shared.fs import _collect_skill_clones, _sync_skills_to_target
from services.api.models.harness_config import create_config, delete_config, list_configs, update_config
from services.api.models.shared.harness import create_item, get_item, get_item_by_id, update_metadata, upsert_item
from services.api.routers.rules import RulesRouter
from services.db import get_connection
from services.proposals.service import persist_proposal, promote_proposal, stage_proposal
from tests.conftest import harness_cleanup

_clean = harness_cleanup('clonever_%')
ORIGINAL = {'body': 'Original rule.', 'metadata': {}}
UPDATED = {'body': 'Updated rule.', 'metadata': {}}


@pytest.fixture(autouse=True)
def clean_proposals():
    yield
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM improvement_proposals WHERE target_name LIKE 'clonever_%'")


def export_clone(directory, name, *, device='', repo='*'):
    skills, repo_skills = _collect_skill_clones('claude', device)
    if repo != '*':
        skills = repo_skills.get(repo, {})
    _sync_skills_to_target(skills, directory, False)
    return directory / name / 'SKILL.md'


def rule(name, clone=True):
    item_id = create_item('rule', name, ORIGINAL, agents=['claude'])
    update_metadata('rule', item_id, clone_as_skill=clone)
    return item_id


def approve_update(name):
    proposal_id = persist_proposal(stage_proposal({
        'target_kind': 'rule', 'action': 'update', 'target_name': name,
        'title': 'Clarify the rule', 'rationale': 'Improve wording without changing deployment.',
        'evidence': [{'source': 'plan', 'id': '12', 'note': 'Synthetic regression fixture'}],
        'body': UPDATED['body'],
    }))
    return proposal_id


def config_fields(item_id):
    rows = [{key: value for key, value in row.items() if key not in {'id', 'item_id', 'created_at', 'updated_at'}}
            for row in list_configs(item_id, 'rule')]
    return sorted(rows, key=lambda row: (row['device'], row['repo'], tuple(row['agents']), row['exclude']))


@pytest.mark.parametrize('clone', [True, False])
def test_clone_rule_content_roundtrip_keeps_choice_and_real_skill_export(tmp_path, clone):
    name = 'clonever_content_' + str(clone).lower()
    item_id = rule(name)
    exported = export_clone(tmp_path / 'skills', name)
    assert exported.read_text() == ORIGINAL['body']
    if not clone:
        update_metadata('rule', item_id, clone_as_skill=False)
    configs = config_fields(item_id)
    app = FastAPI()
    app.include_router(RulesRouter().router, prefix='/harness')
    client = TestClient(app)
    response = client.put(f'/harness/items/rule/{item_id}/content', json={'content': UPDATED})
    assert response.status_code == 200
    new = response.json()
    assert new['id'] != item_id and new['version'] == 2
    assert new['clone_as_skill'] is clone
    assert get_item_by_id('rule', item_id)['content'] == ORIGINAL
    assert config_fields(new['id']) == configs
    listed = client.get('/harness/items/rule', params={'name': name}).json()['items']
    assert len(listed) == 1 and listed[0]['clone_as_skill'] is clone
    exported = export_clone(tmp_path / 'skills', name)
    assert exported.exists() is clone
    if clone:
        assert exported.read_text() == UPDATED['body']


@pytest.mark.parametrize('clone', [True, False])
def test_upsert_keeps_clone_choice_and_deployment_for_real_skill_export(tmp_path, clone):
    name = 'clonever_upsert_' + str(clone).lower()
    item_id = rule(name, clone)
    configs = config_fields(item_id)
    new_id = upsert_item('rule', name, UPDATED, agents=['claude'])
    assert get_item_by_id('rule', new_id)['clone_as_skill'] is clone
    assert config_fields(new_id) == configs
    exported = export_clone(tmp_path / 'skills', name)
    assert exported.exists() is clone
    if clone:
        assert exported.read_text() == UPDATED['body']


@pytest.mark.parametrize('clone', [True, False])
def test_approval_uses_current_clone_choice_instead_of_proposed_snapshot(tmp_path, clone):
    name = 'clonever_proposal_' + str(clone).lower()
    item_id = rule(name, not clone)
    configs = config_fields(item_id)
    proposal_id = approve_update(name)
    update_metadata('rule', item_id, clone_as_skill=clone)
    promoted = promote_proposal(proposal_id)
    new = get_item('rule', name)
    assert new['id'] == promoted['applied_ref']['item_id']
    assert new['clone_as_skill'] is clone
    assert config_fields(new['id']) == configs
    exported = export_clone(tmp_path / 'skills', name)
    assert exported.exists() is clone
    if clone:
        assert exported.read_text() == UPDATED['body']



@pytest.mark.parametrize('path', ['content', 'upsert', 'proposal'])
def test_version_and_configs_roll_back_together_on_copy_failure(monkeypatch, path):
    from services.api.models.shared import harness
    from services.proposals import service

    name = 'clonever_rollback_' + path
    item_id = rule(name)
    original = harness._copy_configs
    attempted = []

    def copy_then_fail(cursor, source_id, new_id, item_type):
        original(cursor, source_id, new_id, item_type)
        attempted.append(new_id)
        raise RuntimeError('abort fixture')

    if path != 'proposal':
        monkeypatch.setattr(harness, '_copy_configs', copy_then_fail)
        with pytest.raises(RuntimeError, match='abort fixture'):
            if path == 'content':
                harness.update_content('rule', item_id, UPDATED)
            else:
                harness.upsert_item('rule', name, UPDATED)
        assert get_item_by_id('rule', attempted[0]) is None
    else:
        proposal_id = approve_update(name)
        monkeypatch.setattr(service, '_copy_configs', copy_then_fail)
        with pytest.raises(RuntimeError, match='abort fixture'):
            promote_proposal(proposal_id)
        proposed = get_item_by_id('rule', attempted[0])
        assert proposed['state'] == 'proposed' and proposed['version'] is None
        assert proposed['clone_as_skill'] is False
    assert list_configs(attempted[0], 'rule') == []
    assert get_item('rule', name)['id'] == item_id
    assert get_item_by_id('rule', item_id)['clone_as_skill'] is True


def test_first_project_upsert_does_not_inherit_the_global_rules_metadata_or_deployment(tmp_path):
    name = 'clonever_project_scope'
    global_id = rule(name)
    config = list_configs(global_id, 'rule')[0]
    update_config(config['id'], device='global-device', repo=str(tmp_path / 'global-repo'))
    global_configs = config_fields(global_id)

    project_id = upsert_item('rule', name, UPDATED, project='project-fixture', agents=['claude'])
    project = get_item_by_id('rule', project_id)
    assert project['version'] == 1 and project['project'] == 'project-fixture'
    assert project['clone_as_skill'] is False
    assert [(row['device'], row['repo']) for row in list_configs(project_id, 'rule')] == [('*', '*')]
    assert get_item('rule', name)['id'] == global_id
    assert config_fields(global_id) == global_configs
    assert export_clone(tmp_path / 'global-skills', name, device='global-device', repo=str(tmp_path / 'global-repo')).read_text() == ORIGINAL['body']
    assert not export_clone(tmp_path / 'project-skills', name).exists()


@pytest.mark.asyncio
async def test_mcp_upsert_applies_creation_defaults_once_and_preserves_multiple_configs_on_update(tmp_path):
    from services.harness.server import mcp

    name = 'clonever_mcp_defaults'
    repo = str(tmp_path / 'fixture-repo')
    arguments = {'name': name, 'item_type': 'rule', 'content': ORIGINAL, 'agents': ['claude'],
                 'device': 'fixture-device', 'repo': repo}
    await mcp.call_tool('harness_upsert', arguments)
    original = get_item('rule', name)
    assert [(row['device'], row['repo']) for row in list_configs(original['id'], 'rule')] == [('fixture-device', repo)]
    update_metadata('rule', original['id'], clone_as_skill=True)
    create_config(original['id'], 'rule', device='fixture-device', repo=str(tmp_path / 'excluded'), agents=['claude'], exclude=True)
    configs = config_fields(original['id'])

    await mcp.call_tool('harness_upsert', {**arguments, 'content': UPDATED,
                                        'device': 'ignored-update-device', 'repo': str(tmp_path / 'ignored-update-repo')})
    updated = get_item('rule', name)
    assert updated['version'] == 2 and updated['clone_as_skill'] is True
    assert config_fields(updated['id']) == configs
    exported = export_clone(tmp_path / 'skills', name, device='fixture-device', repo=repo)
    assert exported.read_text() == UPDATED['body']
    assert not export_clone(tmp_path / 'wrong-skills', name, device='ignored-update-device', repo=repo).exists()


@pytest.mark.parametrize('path', ['content', 'upsert', 'proposal'])
def test_existing_rule_without_configs_stays_unsynced_after_versioning(tmp_path, path):
    from services.api.models.shared.harness import update_content

    name = 'clonever_unsynced_' + path
    item_id = rule(name)
    for config in list_configs(item_id, 'rule'):
        delete_config(config['id'])
    if path == 'content':
        new_id = update_content('rule', item_id, UPDATED)
    elif path == 'upsert':
        new_id = upsert_item('rule', name, UPDATED, agents=['claude'], device='ignored-device', repo='/ignored-repo')
    else:
        new_id = promote_proposal(approve_update(name))['applied_ref']['item_id']
    assert get_item_by_id('rule', new_id)['clone_as_skill'] is True
    assert list_configs(new_id, 'rule') == []
    assert not export_clone(tmp_path / 'skills', name).exists()


@pytest.mark.parametrize('path', ['content', 'upsert', 'proposal'])
def test_versioning_waits_for_a_concurrent_metadata_commit_before_inheriting_the_flag(monkeypatch, tmp_path, path):
    from services.api.models.shared import harness
    from services.proposals import service

    name = 'clonever_locked_' + path
    item_id = rule(name)
    proposal_id = approve_update(name) if path == 'proposal' else None
    module = service if path == 'proposal' else harness
    entered = Event()
    backend = []

    @contextmanager
    def monitored_connection():
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout = '5s'")
            backend.append(conn.get_backend_pid())
            entered.set()
            yield conn

    monkeypatch.setattr(module, 'get_connection', monitored_connection)

    def version():
        if path == 'proposal':
            return promote_proposal(proposal_id)['applied_ref']['item_id']
        if path == 'content':
            return harness.update_content('rule', item_id, UPDATED)
        return upsert_item('rule', name, UPDATED, agents=['claude'])

    with ThreadPoolExecutor(max_workers=1) as executor:
        with get_connection() as blocker, blocker.cursor() as cur:
            cur.execute('UPDATE harness_rules SET clone_as_skill = false WHERE id = %s', (item_id,))
            future = executor.submit(version)
            assert entered.wait(3), 'version writer did not acquire its database connection'
            deadline = time.monotonic() + 3
            while True:
                cur.execute('SELECT pg_blocking_pids(%s)', (backend[0],))
                blockers = cur.fetchone()[0]
                if blocker.get_backend_pid() in blockers:
                    break
                if future.done():
                    future.result()
                    pytest.fail('versioning published before the metadata transaction committed')
                assert time.monotonic() < deadline, f'version writer did not wait for metadata: {blockers}'
                time.sleep(0.01)
        new_id = future.result(timeout=5)

    assert get_item_by_id('rule', item_id)['clone_as_skill'] is False
    assert get_item_by_id('rule', new_id)['clone_as_skill'] is False
    assert not export_clone(tmp_path / 'skills', name).exists()

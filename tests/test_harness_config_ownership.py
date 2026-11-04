from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2.extras import Json

from services.api.models.harness_config import create_config, list_configs
from services.api.models.shared.harness import VALID_TABLES, create_item
from services.api.routers import harness_router
from services.db import get_connection
from tests.conftest import harness_cleanup

CONTENT = {"body": "Synthetic configuration ownership fixture", "metadata": {}}
_clean = harness_cleanup("cfg_owner_%")


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(harness_router, prefix="/harness")
    return TestClient(app)


def item(kind, suffix):
    return create_item(kind, "cfg_owner_" + suffix, CONTENT, agents=["codex"])


def cross_kind_pair(kind):
    other_kind = next(value for value in VALID_TABLES if value != kind)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT GREATEST("
            + ",".join(
                f"COALESCE((SELECT MAX(id) FROM {table}),0)"
                for table in VALID_TABLES.values()
            )
            + ")+1"
        )
        item_id = cur.fetchone()[0]
        for value in (kind, other_kind):
            cur.execute(
                f"INSERT INTO {VALID_TABLES[value]} (id,name,content,agents,subagents,sort_key,enabled,version) "
                "VALUES (%s,%s,%s,%s,%s,0,true,1)",
                (item_id, "cfg_owner_cross_" + value, Json(CONTENT), ["codex"], []),
            )
    create_config(item_id, kind, agents=["codex"])
    create_config(item_id, other_kind, agents=["codex"])
    return item_id, other_kind


def mutate(client, method, kind, parent_id, config_id):
    path = f"/harness/items/{kind}/{parent_id}/configs/{config_id}"
    if method == "patch":
        return client.patch(path, json={"enabled": False, "device": "wrong-parent"})
    return client.delete(path)


@pytest.mark.parametrize("kind", list(VALID_TABLES))
@pytest.mark.parametrize("method", ["patch", "delete"])
@pytest.mark.parametrize(
    "mismatch", ["other_item", "other_kind", "missing_config", "missing_parent"]
)
def test_nested_config_rejects_foreign_or_missing_identity_without_mutation(
    client, kind, method, mismatch
):
    if mismatch == "other_kind":
        parent_id, other_kind = cross_kind_pair(kind)
        other_id = parent_id
    else:
        parent_id, other_id = item(kind, "parent"), item(kind, "other")
        other_kind = kind
    parent_configs = list_configs(parent_id, kind)
    other_configs = list_configs(other_id, other_kind)
    config_id = other_configs[0]["id"]
    requested_parent = parent_id
    if mismatch == "missing_config":
        config_id = 2_147_483_647
    elif mismatch == "missing_parent":
        requested_parent = 2_147_483_647
    response = mutate(client, method, kind, requested_parent, config_id)
    assert response.status_code == 404, response.text
    assert list_configs(parent_id, kind) == parent_configs
    assert list_configs(other_id, other_kind) == other_configs


@pytest.mark.parametrize("kind", list(VALID_TABLES))
@pytest.mark.parametrize("method", ["patch", "delete"])
def test_nested_config_valid_mutation_preserves_other_parent(client, kind, method):
    parent_id, other_id = item(kind, "valid"), item(kind, "untouched")
    config_id = list_configs(parent_id, kind)[0]["id"]
    before = list_configs(other_id, kind)
    response = mutate(client, method, kind, parent_id, config_id)
    assert response.status_code == 200, response.text
    if method == "patch":
        assert response.json()[0]["enabled"] is False
        assert response.json()[0]["device"] == "wrong-parent"
    else:
        assert response.json() == {"deleted": config_id}
        assert list_configs(parent_id, kind) == []
    assert list_configs(other_id, kind) == before


@pytest.mark.parametrize("kind", list(VALID_TABLES))
def test_nested_config_empty_patch_keeps_existing_validation(client, kind):
    parent_id = item(kind, "empty")
    before = list_configs(parent_id, kind)
    response = client.patch(
        f"/harness/items/{kind}/{parent_id}/configs/{before[0]['id']}", json={}
    )
    assert response.status_code == 422
    assert list_configs(parent_id, kind) == before

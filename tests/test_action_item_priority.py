from uuid import uuid4

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

from services.action_items import db, queue_db
from services.action_items.contracts import (
    Create,
    Patch,
    Query,
    ItemCreate,
    ItemPatch,
    ItemQuery,
)
from services.db import get_connection
from tests.test_action_items import (
    action_items_empty as action_items_empty,
    client as client,
)
from tests.test_action_item_epics import epic, membership, current
from tests.test_action_items_server import call
from tests.test_profile_discussion_queue import owners as owners

pytestmark = pytest.mark.usefixtures("action_items_empty")


def test_priority_persists_without_reordering_and_old_create_receipts_replay():
    payload = {"title": "Plan today", "request_id": str(uuid4())}
    first = db.create(payload)
    other = db.create({"title": "Later"})
    assert first["is_priority"] is False
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT create_payload FROM action_items WHERE id=%s", (first["id"],)
        )
        assert "is_priority" not in cursor.fetchone()[0]
    marked = db.update(
        first["id"], {"expected_revision": first["revision"], "is_priority": True}
    )
    assert marked["is_priority"] is True and marked["revision"] == first["revision"] + 1
    assert (
        marked["priority"] == first["priority"]
        and db.get(other["id"])["priority"] == other["priority"]
    )
    assert db.create({**payload, "is_priority": False}) == marked
    with pytest.raises(db.Conflict):
        db.create({**payload, "is_priority": True})
    assert (
        db.update(
            marked["id"], {"expected_revision": marked["revision"], "is_priority": True}
        )
        == marked
    )
    with pytest.raises(db.Conflict):
        db.update(
            marked["id"], {"expected_revision": first["revision"], "is_priority": False}
        )
    for changes in (
        {"description": "Keep the flag"},
        {"status": "completed"},
        {"status": "open"},
    ):
        marked = db.update(
            marked["id"], {"expected_revision": marked["revision"], **changes}
        )
        assert marked["is_priority"] is True
    group = epic(item=marked)
    assert db.get(marked["id"])["is_priority"] is True
    latest = current(group["id"])
    queue_db.remove_epic(
        group["id"],
        {"expected_revision": latest["revision"], "cohort": latest["cohort"]},
    )
    assert db.get(marked["id"])["is_priority"] is True
    unmarked = db.update(
        marked["id"],
        {"expected_revision": db.get(marked["id"])["revision"], "is_priority": False},
    )
    assert unmarked["is_priority"] is False


@pytest.mark.parametrize("bad", [None, 0, 1, "true", "false", [], {}])
def test_priority_booleans_are_strict(bad):
    with pytest.raises(ValidationError):
        Create.model_validate({"title": "Task", "is_priority": bad})
    with pytest.raises(ValidationError):
        Patch.model_validate({"expected_revision": 1, "is_priority": bad})
    with pytest.raises(ValidationError):
        Query.model_validate({"priority_only": bad})


def test_priority_filters_before_count_paging_and_keeps_only_matching_epic_children(
    client,
):
    ordinary = db.create({"title": "Ordinary", "project": "Work"})
    marked = [
        db.create({"title": f"Marked {i}", "project": "Work", "is_priority": True})
        for i in range(3)
    ]
    group = epic(item=marked[1])
    membership(ordinary, destination=current(group["id"]))
    epic("Empty group")
    expected = [row["id"] for row in db.list_items({"priority_only": True})["items"]]
    flat = db.list_items({"priority_only": True, "limit": 1, "offset": 1})
    assert flat["total"] == 3 and [row["id"] for row in flat["items"]] == expected[1:2]
    for kind in ("all", "epic", "item", "task"):
        result = queue_db.list_queue(
            {"kind": kind, "priority_only": True, "project": "Work"}
        )
        tasks = [
            item
            for root in result["items"]
            for item in ([root] if root["kind"] == "item" else root["children"])
        ]
        assert tasks and all(task["item"]["is_priority"] for task in tasks)
        assert all(
            root["kind"] != "epic" or root["children"] for root in result["items"]
        )
    grouped = queue_db.list_queue({"priority_only": True, "kind": "epic"})["items"][0]
    assert grouped["matching_count"] == 1 and grouped["total_count"] == 2
    assert grouped["children"][0]["item"]["id"] == marked[1]["id"]
    for endpoint in ("/api/action-items", "/api/action-items/queue"):
        response = client.get(endpoint, params={"priority_only": "true"})
        assert response.status_code == 200 and response.json()["total"] == 3
        for bad in ("1", "0", "True", "yes", ""):
            assert (
                client.get(endpoint, params={"priority_only": bad}).status_code == 422
            )
    assert (
        client.patch(
            f"/api/action-items/{marked[0]['id']}",
            json={"expected_revision": 1, "is_priority": None},
        ).status_code
        == 422
    )


def test_profile_discussion_contracts_and_read_shape_remain_unchanged(owners):
    queue = db.profile_queue(owners[0]["id"])
    topic = queue.create({"title": "Discussion"})
    assert (
        "is_priority" not in topic
        and "is_priority" not in queue.list_items()["items"][0]
    )
    for model, payload in [
        (ItemCreate, {"title": "Topic", "is_priority": True}),
        (ItemPatch, {"expected_revision": 1, "is_priority": False}),
        (ItemQuery, {"priority_only": True}),
    ]:
        with pytest.raises(ValidationError):
            model.model_validate(payload)
    with pytest.raises(ValueError):
        queue.update(
            topic["id"], {"expected_revision": topic["revision"], "is_priority": True}
        )
    with pytest.raises(ValueError):
        queue.list_items({"priority_only": True})


@pytest.mark.asyncio
async def test_actual_mcp_priority_create_patch_and_filter_forward_strict_values():
    created = await call("action_item_create", title="Agent plan", is_priority=True)
    await call("action_item_create", title="Unmarked task")
    assert created["is_priority"] is True
    assert (await call("action_item_list", priority_only=True))["total"] == 1
    assert (
        await call(
            "action_item_queue_list", filters={"priority_only": True, "kind": "task"}
        )
    )["total"] == 1
    changed = await call(
        "action_item_update",
        item_id=created["id"],
        changes={"expected_revision": created["revision"], "is_priority": False},
    )
    assert (
        changed["is_priority"] is False and changed["priority"] == created["priority"]
    )
    assert (await call("action_item_list", priority_only=True))["total"] == 0
    for tool, arguments in [
        ("action_item_create", {"title": "Bad", "is_priority": 1}),
        ("action_item_list", {"priority_only": "true"}),
    ]:
        with pytest.raises(ToolError):
            await call(tool, **arguments)

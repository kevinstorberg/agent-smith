from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.models import audit, evals, plan, proposal
from services.api.models.shared.harness import create_item, list_items_summary
from services.api.routers import chat as chat_router, eval_suites, evals as results_router, jobs, plans
from services.api.routers.rules import RulesRouter
from services.chat import service as chat
from services.db import get_connection
from services.meetings import db as meetings, vocabulary_db
from services.meetings.config import SourceConfig
from services.meetings.types import MeetingSummary
from tests.conftest import clean_harness_rows, clean_meeting_rows


@pytest.fixture
def marker():
    value = "CONTROLTEST " + uuid4().hex
    yield value
    with get_connection() as conn, conn.cursor() as cur:
        for table, column in (("eval_results", "eval_type"), ("improvement_proposals", "title"),
                              ("chat_rooms", "topic"), ("eval_suites", "name"), ("plans", "title"),
                              ("tool_call_events", "session_id"), ("meeting_vocabulary", "term")):
            cur.execute(f"DELETE FROM {table} WHERE {column} LIKE %s", (value + "%",))
    clean_harness_rows(value + "%")
    clean_meeting_rows(value)


def test_harness_controls_apply_to_all_five_types_with_stable_global_order(marker):
    for item_type in ("rule", "skill", "tool", "hook", "agent"):
        for index, name in enumerate(("Zebra", "Alpha", "Middle")):
            create_item(item_type, marker + " " + name, {"body": "fixture", "metadata": {}}, agents=["claude"], enabled=index != 0)
        rows = list_items_summary(item_type, agent="claude", sort="name", enabled=False)
        assert [row["name"] for row in rows if row["name"].startswith(marker)] == [marker + " Zebra"]
        ordered = [row["name"] for row in list_items_summary(item_type, sort="name") if row["name"].startswith(marker)]
        assert ordered == sorted(ordered, key=str.lower)
        with pytest.raises(ValueError):
            list_items_summary(item_type, sort="not-a-column")


def test_plan_listing_reaches_beyond_old_search_cap_and_filters_before_page(marker):
    for index in range(105):
        plan.create_plan(f"{marker} {index:03}", "fixture", project=marker)
    rows, total = plan.list_plans(project=marker, q=marker, sort="title", limit=10, offset=100)
    assert total == 105
    assert [row["title"] for row in rows] == [f"{marker} {index:03}" for index in range(100, 105)]
    app = FastAPI()
    app.include_router(plans.router, prefix="/plans")
    response = TestClient(app).get("/plans", params={"q": marker, "sort": "title", "limit": 10, "offset": 100})
    assert response.status_code == 200
    assert response.json()["total"] == 105 and len(response.json()["items"]) == 5


def test_suite_filters_and_page_reach_beyond_default_fifty(marker):
    for index in range(51):
        evals.create_suite(f"{marker} {index:03}", "rules", "controls", "fixture", enabled=index != 50)
    rows, total = evals.list_suites(enabled_only=False, q=marker, sort="name", limit=10, offset=50)
    assert total == 51 and rows[0]["name"].endswith("050")
    disabled, total = evals.list_suites(q=marker, enabled=False, limit=1)
    assert total == 1 and not disabled[0]["enabled"]
    app = FastAPI()
    app.include_router(eval_suites.router)
    response = TestClient(app).get("/suites", params={"q": marker, "enabled": "false"})
    assert response.status_code == 200 and response.json()["total"] == 1


def test_chat_search_state_and_paging_use_complete_room_list(marker):
    for index in range(51):
        room = chat.create_room(f"{marker} {index:03}", "matching context")
    chat.stop_agent_access(room["id"])
    rows, total = chat.list_rooms(q=marker, sort="name", limit=10, offset=50)
    assert total == 51 and rows[0]["id"] == room["id"]
    closed, total = chat.list_rooms(q=marker, status="closed", limit=1)
    assert total == 1 and closed[0]["id"] == room["id"]
    assert chat.list_rooms(q=marker, status="open", limit=1)[1] == 50


def test_proposals_search_and_status_before_page(marker):
    ids = []
    for name in ("Zebra", "Alpha", "Middle"):
        ids.append(proposal.ProposalModel.create(
            title=marker + " " + name, target_kind="rule", target_name=marker + " target", action="create",
            proposed_item_id=1, rationale="fixture", fingerprint=uuid4().hex,
        ))
    proposal.ProposalModel.dynamic_update(ids[1], {"status": "rejected"})
    rows, total = proposal.list_proposals(status="pending", q=marker, sort="title", limit=1)
    assert total == 2 and rows[0]["title"] == marker + " Middle"


def test_audit_metadata_search_and_duration_sort_before_page(marker):
    for index in range(12):
        audit.start_event("claude", marker, "Read", marker + str(index), {})
    matching = audit.start_event("codex", marker, "SpecialTool", marker + " match", {})
    audit.complete_event(marker + " match", status="success", duration_ms=200)
    rows, total = audit.list_events(q="SpecialTool", session_id=marker, sort="duration", limit=1)
    assert total == 1 and rows[0]["id"] == matching and rows[0]["duration_ms"] == 200


def test_meeting_title_and_chronological_order_before_pagination(marker):
    config = SourceConfig(marker, "test", marker, "fixture")
    meetings.claim_source(config, "run")
    for index, title in enumerate(("Zebra", "Alpha", "Middle")):
        stamp = datetime(2026, 1, index + 1, tzinfo=timezone.utc)
        summary = MeetingSummary(str(index), marker + " " + title, "fixture", None, "https://example.invalid", stamp, stamp)
        meetings.save_progress(config, "run", {}, summary=summary)
    title = meetings.list_summaries(query=marker, sort="title", limit=1)
    assert title["total"] == 3 and title["items"][0]["title"] == marker + " Alpha"
    oldest = meetings.list_summaries(query=marker, sort="oldest", limit=1)
    assert oldest["items"][0]["title"] == marker + " Zebra"


def test_vocabulary_definition_filter_counts_before_page_and_preserves_agent_list(marker):
    vocabulary_db.create(marker + " Alpha", "")
    middle = vocabulary_db.create(marker + " Middle", "a meaning")
    vocabulary_db.create(marker + " Zebra", "another meaning")
    result = vocabulary_db.list_terms(query=marker, definition="defined", sort="term", limit=1)
    assert result["total"] == 2 and result["items"][0]["id"] == middle["id"]
    assert vocabulary_db.list_terms(query=marker, definition="undefined")["total"] == 1
    assert vocabulary_db.list_terms(query=marker)["total"] == 3
    assert vocabulary_db.list_terms(query=marker, sort="updated", limit=1)["items"][0]["term"].endswith("Zebra")


def test_results_facets_search_charts_and_sort_share_all_matching_rows(marker):
    from evals.shared.db import save_result

    for index in range(12):
        save_result(timestamp=datetime(2026, 1, index + 1, tzinfo=timezone.utc), eval_type=marker, subcategory="group",
                    scenario=f"scenario-{index:02}", test_model=f"model-{index:02}", judge_model="fixture", threshold=0.5,
                    output="fixture", results=[{"rule": "rule", "score": index / 12}])
    args = {"scenario": "", "model": "", "eval_type": marker, "subcategory": "", "date_from": "", "date_to": ""}
    page = results_router.list_evals(**args, limit=1, offset=0, sort="score")
    assert page["total"] == 12 and page["items"][0]["scenario"] == "scenario-11"
    facets = results_router.result_facets(eval_type=marker)
    assert len(facets["scenarios"]) == len(facets["models"]) == 12
    assert "scenario-00" in facets["scenarios"]
    searched = results_router.list_evals(**args, q="scenario-10", limit=1, offset=0)
    assert searched["total"] == 1
    chart = results_router.chart_average(scenario="", model="", eval_type=marker, subcategory="", q="scenario-10")
    assert len(chart) == 1 and chart[0]["id"] == searched["items"][0]["id"]
    assert results_router.result_facets(eval_type=marker, q="scenario-10")["models"] == ["model-10"]


@pytest.mark.parametrize("router,path,parameter", [(jobs.router, "/", "q"), (plans.router, "/", "q"),
    (eval_suites.router, "/suites", "q"), (chat_router.router, "/", "q"), (RulesRouter().router, "/items/rule", "name")])
def test_resource_query_boundaries_reject_oversized_search(router, path, parameter):
    app = FastAPI()
    app.include_router(router, prefix="/resource")
    assert TestClient(app).get("/resource" + path, params={parameter: "x" * 1001}).status_code == 422

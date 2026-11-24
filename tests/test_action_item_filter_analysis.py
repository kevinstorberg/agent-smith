from __future__ import annotations

import pytest

from services.meetings import action_item_filter as filtering
from services.meetings.action_item_analysis import ActionItemAnalysisError
from tests.test_meeting_action_item_analysis import NEW, SNAPSHOT, model as model
from tests.test_meeting_memory_agent import call


def record(status="pending", *, stale=False):
    return {
        "key": "proposal:1",
        "kind": "proposal",
        "data": {
            "id": 1,
            "status": status,
            "title": "Full original proposed fields",
            "changes": {
                "title": "Send vendor readiness list",
                "description": "TAIL-FULL-ORIGINAL-DESCRIPTION",
            },
            "rationale": "TAIL-FULL-RATIONALE",
            "evidence": [{"quote": "Exact older evidence"}],
            "before_snapshot": None,
            "source_stale": stale,
            "target_stale": False,
        },
    }


def decision(index=0, *, matches=None, actionable=True):
    return {
        "candidate_id": index,
        "actionable": actionable,
        "matches": matches or [],
        "rationale": "Compared the requested work and current desired state",
        "evidence": NEW["evidence"],
    }


def data(records):
    return filtering.windows(
        SNAPSHOT, [NEW], records, {"0": [{"key": r["key"]} for r in records]}
    )[0]


@pytest.mark.asyncio
async def test_action_item_filter_real_tool_loop_receives_full_original_records(model):
    instance = model(
        call(
            "filter_action_items",
            items=[decision(matches=[{"key": "proposal:1", "relation": "same"}])],
        )
    )
    result = await filtering.analyze_window(SNAPSHOT, data([record("rejected")]))
    assert (
        filtering.reduce_decisions([NEW], [record("rejected")], [result])["keep"] == []
    )
    assert "TAIL-FULL-ORIGINAL-DESCRIPTION" in str(instance.seen)
    assert "TAIL-FULL-RATIONALE" in str(instance.seen)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        [decision(99)],
        [decision(), decision()],
        [decision(matches=[{"key": "proposal:999", "relation": "same"}])],
        [{**decision(), "changes": {"title": "Invented work"}}],
        [
            {
                **decision(),
                "evidence": [{"segment_id": "summary-0", "quote": "Invented quote"}],
            }
        ],
    ],
)
async def test_action_item_filter_rejects_unsafe_outputs_before_corrected_submission(
    model, bad
):
    instance = model(
        call("filter_action_items", items=bad),
        call("filter_action_items", items=[decision()]),
    )
    result = await filtering.analyze_window(SNAPSHOT, data([record()]))
    assert result["items"][0]["matches"] == []
    assert len(instance.seen) == 2


@pytest.mark.parametrize(
    "status,stale,expected_keep,expected_supersede",
    [
        ("rejected", False, [], []),
        ("pending", False, [], []),
        ("pending", True, [0], [{"proposal_id": 1, "replacement": "candidate:0"}]),
        ("approved", False, [0], []),
        ("superseded", False, [0], []),
    ],
)
def test_action_item_filter_reduction_preserves_review_state_semantics(
    status, stale, expected_keep, expected_supersede
):
    rows = [record(status, stale=stale)]
    result = filtering.reduce_decisions(
        [NEW],
        rows,
        [{"items": [decision(matches=[{"key": "proposal:1", "relation": "same"}])]}],
    )
    assert result["keep"] == expected_keep and result["supersede"] == expected_supersede


def test_action_item_filter_preserves_saved_desired_state_and_distinct_work():
    row = {
        "key": "task:7",
        "kind": "task",
        "data": {"id": 7, "title": "Send checklist", "status": "open"},
    }
    same = {"items": [decision(matches=[{"key": "task:7", "relation": "same"}])]}
    different = {"items": [decision()]}
    assert filtering.reduce_decisions([NEW], [row], [same])["keep"] == []
    assert filtering.reduce_decisions([NEW], [row], [different])["keep"] == [0]


def test_action_item_filter_same_batch_relations_choose_one_without_cycles():
    rows = [
        {"key": f"candidate:{i}", "kind": "candidate", "data": NEW} for i in range(2)
    ]
    result = {
        "items": [
            decision(0, matches=[{"key": "candidate:1", "relation": "same"}]),
            decision(1, matches=[{"key": "candidate:0", "relation": "same"}]),
        ]
    }
    assert filtering.reduce_decisions([NEW, NEW], rows, [result])["keep"] == [0]


def test_action_item_filter_no_action_creates_drop_but_grounded_completion_updates_survive():
    for candidate in [
        NEW,
        {**NEW, "changes": {"title": "Already completed", "status": "completed"}},
    ]:
        assert (
            filtering.reduce_decisions(
                [candidate], [], [{"items": [decision(actionable=False)]}]
            )["keep"]
            == []
        )
    completed = {
        **NEW,
        "changes": {"title": "Already completed", "status": "completed"},
    }
    assert (
        filtering.reduce_decisions([completed], [], [{"items": [decision()]}])["keep"]
        == []
    )
    update = {
        **completed,
        "action": "update",
        "target_id": 7,
        "expected_revision": 1,
        "changes": {"status": "completed"},
    }
    assert filtering.reduce_decisions([update], [], [{"items": [decision()]}])[
        "keep"
    ] == [0]


def test_action_item_filter_indeterminate_fails_closed():
    with pytest.raises(ActionItemAnalysisError, match="indeterminate"):
        filtering.reduce_decisions(
            [NEW],
            [record()],
            [
                {
                    "items": [
                        decision(
                            matches=[{"key": "proposal:1", "relation": "indeterminate"}]
                        )
                    ]
                }
            ],
        )


def test_action_item_filter_windows_do_not_truncate_or_omit_late_records():
    records = [
        {
            **record(),
            "key": f"proposal:{i}",
            "data": {**record()["data"], "rationale": "x" * 2000},
        }
        for i in range(205)
    ]
    result = filtering.windows(
        SNAPSHOT, [NEW], records, {"0": [{"key": r["key"]} for r in records]}
    )
    assert len(result) > 1
    assert [r["key"] for window in result for r in window["comparison_records"]] == [
        r["key"] for r in records
    ]
    assert result[-1]["comparison_records"][-1]["data"]["rationale"] == "x" * 2000


@pytest.mark.parametrize(
    "scenario", ["actionability", "group_relation", "competing_replacements"]
)
def test_action_item_filter_rejects_contradictory_decisions_before_publication(
    scenario,
):
    candidate_rows = [
        {"key": f"candidate:{index}", "kind": "candidate", "data": NEW}
        for index in range(2)
    ]
    pending = record(stale=True)
    if scenario == "actionability":
        candidates, rows = [NEW], [pending]
        outcomes = [{"items": [decision()]}, {"items": [decision(actionable=False)]}]
    elif scenario == "group_relation":
        candidates, rows = [NEW, NEW], [pending, *candidate_rows]
        outcomes = [
            {
                "items": [
                    decision(
                        0,
                        matches=[
                            {"key": "candidate:1", "relation": "same"},
                            {"key": "proposal:1", "relation": "same"},
                        ],
                    ),
                    decision(1, matches=[{"key": "proposal:1", "relation": "replace"}]),
                ]
            }
        ]
    else:
        candidates, rows = [NEW, NEW], [pending, *candidate_rows]
        outcomes = [
            {
                "items": [
                    decision(
                        index, matches=[{"key": "proposal:1", "relation": "replace"}]
                    )
                    for index in range(2)
                ]
            }
        ]
    with pytest.raises(ActionItemAnalysisError):
        filtering.reduce_decisions(candidates, rows, outcomes)


def test_action_item_filter_late_import_older_meeting_cannot_replace_newer_pending_work():
    from services.meetings.action_item_filter import FilterDecision

    prior = record()
    prior["data"]["created_at"] = "2026-11-19T12:00:00+00:00"
    prior["data"]["source_timing"] = {
        "meeting_start": "2026-11-20T12:00:00+00:00",
        "provider_created_at": "2026-11-20T13:00:00+00:00",
    }
    older = {
        **SNAPSHOT,
        "meeting_start": "2026-11-18T12:00:00+00:00",
        "provider_created_at": "2026-11-18T13:00:00+00:00",
        "first_seen_at": "2026-11-24T12:00:00+00:00",
    }
    window = filtering.windows(older, [NEW], [prior], {"0": [{"key": "proposal:1"}]})[0]
    output = FilterDecision.model_validate(
        decision(matches=[{"key": "proposal:1", "relation": "replace"}])
    )
    assert "older meeting" in filtering.validate_decisions([output], window).lower()

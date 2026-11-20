from __future__ import annotations

import pytest

from scripts.check_action_item_actionability import CASES, main, verify_result


def test_live_check_requires_explicit_opt_in_before_model_initialization(monkeypatch):
    monkeypatch.setattr("sys.argv", ["check_action_item_actionability"])
    monkeypatch.setattr(
        "scripts.check_action_item_actionability.live_evals_enabled", lambda: False
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def test_actionability_check_rejects_false_positives_and_lost_actions():
    pending = CASES[0]
    verify_result(pending, {"items": []})
    with pytest.raises(AssertionError, match="Status-only"):
        verify_result(pending, {"items": [{"action": "create"}]})
    with pytest.raises(AssertionError, match="Expected one create"):
        verify_result(CASES[3], {"items": []})


def test_completion_check_rejects_creating_new_work_or_overwriting_manual_fields():
    case = next(case for case in CASES if case.name == "completion")
    valid = {"action": "update", "target_id": 7, "changes": {"status": "completed"}}
    verify_result(case, {"items": [valid]})
    with pytest.raises(AssertionError, match="Expected one update"):
        verify_result(case, {"items": [{**valid, "action": "create"}]})
    with pytest.raises(AssertionError, match="minimally"):
        verify_result(
            case,
            {
                "items": [
                    {
                        **valid,
                        "changes": {"status": "completed", "description": "replaced"},
                    }
                ]
            },
        )

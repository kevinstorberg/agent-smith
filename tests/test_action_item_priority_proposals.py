import pytest

from services.action_items import db, proposals
from services.action_items.proposal_contracts import TASK_FIELDS
from tests.test_action_item_proposals import (
    source_factory as source_factory,
    source as source,
    empty_task_proposals as empty_task_proposals,
    candidate,
)


def test_unrelated_proposal_changes_preserve_priority_and_old_field_identities(source):
    marked = db.create({"title": "Review", "is_priority": True})
    assert set(proposals._task_values(marked)) == TASK_FIELDS
    assert "is_priority" not in proposals._prepare_candidate(source, candidate())[2]
    review = proposals.stage_and_persist(
        source, candidate(target=marked, changes={"description": "Reviewed detail"})
    )
    proposals.promote_proposal(review["id"])
    updated = db.get(marked["id"])
    assert updated["is_priority"] is True and updated["priority"] == marked["priority"]
    assert updated["description"] == "Reviewed detail"


def test_priority_change_stales_an_older_proposal_without_automatic_reset(source):
    task = db.create({"title": "Review"})
    review = proposals.stage_and_persist(
        source, candidate(target=task, changes={"description": "Older review"})
    )
    marked = db.update(
        task["id"], {"expected_revision": task["revision"], "is_priority": True}
    )
    with pytest.raises(proposals.ProposalConflictError):
        proposals.promote_proposal(review["id"])
    assert db.get(task["id"]) == marked

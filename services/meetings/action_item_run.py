from __future__ import annotations

from copy import deepcopy

from services.meetings import action_item_analysis, action_item_db, processing
from services.action_items.proposal_contracts import (
    ActionItemContextTooLarge,
    MAX_CONTEXT_ITEMS,
)
from services.meetings.digestion import configured_sources
from services.meetings.service import run_db
from services.action_items.proposals import decision_context, stage_and_persist
from services.proposals.errors import DuplicateProposalError, ProposalConflictError


class ActionItemRun(processing.ProcessingRun):
    def __init__(
        self, source: str | None = None, *, deadline: float | None = None
    ) -> None:
        super().__init__(
            action_item_db.release_owner, get_record=action_item_db.get_record
        )
        self.source = source
        self.graph_deadline = deadline
        self.report: dict = {"outcome": "idle"}

    async def __aenter__(self):
        await super().__aenter__()
        if self.graph_deadline is not None:
            self.deadline = min(self.deadline, self.graph_deadline)
        return self

    async def prepare(self) -> None:
        self.record = await run_db(
            action_item_db.claim, list(configured_sources(self.source)), self.owner
        )

    async def generate_proposals(self) -> None:
        if self.record:
            await self.run_stage(
                "action_items", self.report, self._work, action_item_db.record_failure
            )

    async def _work(self, record: dict, *, deadline: float) -> None:
        key = record["meeting_id"]
        artifact = deepcopy(record["action_items_artifact"])
        if "items" in artifact:
            _validate_checkpoint(artifact, record)

        async def validate_source() -> None:
            await run_db(action_item_db.assert_current, key, self.owner)

        if "items" not in artifact:
            inventory, projects = await run_db(action_item_db.inventory)
            prior = await run_db(decision_context, MAX_CONTEXT_ITEMS)
            if prior["total"] > MAX_CONTEXT_ITEMS or prior["total"] != len(
                prior["items"]
            ):
                raise ActionItemContextTooLarge(
                    "The complete proposal history exceeds 200 items; no partial matching was attempted"
                )
            snapshot = deepcopy(record["snapshot"])
            result = await action_item_analysis.analyze_action_items(
                snapshot,
                inventory,
                prior["items"],
                projects,
                deadline=deadline,
                validate_context=validate_source,
            )
            artifact = {
                "items": result["items"],
                "reason": result.get("reason", ""),
                "input_snapshot": snapshot,
                "input_hash": record["source_hash"],
                "total_units": len(result["items"]),
                "offset": 0,
                "published_ids": artifact.get("published_ids", []),
                "skipped_count": 0,
            }
            await run_db(action_item_db.save_progress, key, self.owner, artifact)
        while artifact["offset"] < len(artifact["items"]):
            await validate_source()
            item = artifact["items"][artifact["offset"]]
            try:
                await run_db(
                    stage_and_persist,
                    artifact["input_snapshot"],
                    item,
                    lease_owner=self.owner,
                )
            except DuplicateProposalError:
                artifact["skipped_count"] += 1
            except ProposalConflictError:
                retained = await run_db(
                    action_item_db.proposal_ids, artifact["input_snapshot"]
                )
                await run_db(
                    action_item_db.save_progress,
                    key,
                    self.owner,
                    {"published_ids": retained},
                )
                raise
            artifact["offset"] += 1
            artifact["published_ids"] = await run_db(
                action_item_db.proposal_ids, artifact["input_snapshot"]
            )
            await run_db(action_item_db.save_progress, key, self.owner, artifact)
        await run_db(
            action_item_db.save_progress, key, self.owner, artifact, complete=True
        )
        self.report.update(
            outcome="done",
            proposals=len(artifact["published_ids"]),
            skipped=artifact["skipped_count"],
        )


def _validate_checkpoint(artifact: dict, record: dict) -> None:
    items, offset = artifact.get("items"), artifact.get("offset")
    snapshot = artifact.get("input_snapshot")
    if (
        not isinstance(items, list)
        or len(items) > 20
        or any(not isinstance(item, dict) for item in items)
        or type(offset) is not int
        or not 0 <= offset <= len(items)
        or type(artifact.get("total_units")) is not int
        or artifact.get("total_units") != len(items)
        or not isinstance(artifact.get("published_ids"), list)
        or any(
            type(key) is not int or key <= 0
            for key in artifact.get("published_ids", [])
        )
        or type(artifact.get("skipped_count")) is not int
        or not 0 <= artifact["skipped_count"] <= offset
        or not isinstance(snapshot, dict)
        or snapshot.get("id") != record["meeting_id"]
        or type(snapshot.get("revision")) is not int
        or snapshot.get("revision") != record["source_revision"]
        or snapshot.get("content_hash") != record["source_hash"]
        or snapshot.get("summary_text") != record["snapshot"]["summary_text"]
        or artifact.get("input_hash") != record["source_hash"]
    ):
        raise ValueError(
            "Saved Action Item checkpoint is invalid; generate fresh proposals"
        )

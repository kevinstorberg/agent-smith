from __future__ import annotations

from copy import deepcopy
from importlib.metadata import version

from services.action_items import matching, proposal_corpus, proposals
from services.action_items.proposal_contracts import ActionItemCandidate
from services.config import MEMORY_EMBEDDING_DIMENSION, MEMORY_EMBEDDING_MODEL
from services.memory.db import get_embeddings, get_memory_token_budget
from services.meetings import action_item_filter
from services.proposals.errors import ProposalConflictError

from services.meetings import action_item_analysis, action_item_db, processing
from services.meetings.digestion import configured_sources
from services.meetings.service import run_db


class ActionItemRun(processing.ProcessingRun):
    def __init__(
        self, source: str | None = None, *, deadline: float | None = None
    ) -> None:
        super().__init__(
            action_item_db.release_owner, get_record=action_item_db.get_record
        )
        self.owner = "v2:" + self.owner
        self.source = source
        self.graph_deadline = deadline
        self.report: dict = {"outcome": "idle"}

    async def __aenter__(self):
        await super().__aenter__()
        if self.graph_deadline is not None:
            self.deadline = min(self.deadline, self.graph_deadline)
        return self

    async def prepare(self) -> None:
        identities = list(configured_sources(self.source))
        self.record = await run_db(action_item_db.claim, identities, self.owner)

    async def generate_candidates(self) -> None:
        if self.record:
            await self.run_stage(
                "action_items",
                self.report,
                self._generate,
                action_item_db.record_failure,
            )
            self.record = await run_db(
                action_item_db.get_record, self.record["meeting_id"]
            )
            artifact = self.record["action_items_artifact"]
            if artifact.get("version") == 2:
                self.report.update(
                    phase=artifact["phase"], generated=len(artifact["items"])
                )

    async def filter_candidates(self) -> None:
        if self.report.get("outcome") == "failed":
            return
        if self.record and self.record["action_items_artifact"].get("phase") in {
            "generated",
            "filtering",
            "publishing",
        }:
            await self.run_stage(
                "action_items",
                self.report,
                self._filter_and_publish,
                action_item_db.record_failure,
            )

    async def generate_proposals(self) -> None:
        await self.generate_candidates()
        await self.filter_candidates()

    async def _generate(self, record: dict, *, deadline: float) -> None:
        key = record["meeting_id"]
        artifact = deepcopy(record["action_items_artifact"])
        if "items" in artifact:
            _validate_checkpoint(artifact, record)
            if artifact.get("version") == 2:
                return
            completed_prefix = artifact["offset"]
            remaining = artifact["items"][completed_prefix:]
            artifact.update(
                version=2,
                phase="generated",
                work_units=completed_prefix + 1,
                items=remaining,
                offset=0,
                total_units=len(remaining),
                legacy_prefix_count=completed_prefix,
                legacy_skipped_count=artifact["skipped_count"],
                skipped_count=0,
            )
            await run_db(action_item_db.save_progress, key, self.owner, artifact)
            return

        async def validate_source() -> None:
            await run_db(action_item_db.assert_current, key, self.owner)

        inventory, projects = await run_db(action_item_db.inventory)
        snapshot = deepcopy(record["snapshot"])
        result = await action_item_analysis.analyze_action_items(
            snapshot,
            inventory,
            [],
            projects,
            deadline=deadline,
            validate_context=validate_source,
        )
        artifact = {
            "version": 2,
            "phase": "generated",
            "items": result["items"],
            "reason": result.get("reason", ""),
            "input_snapshot": snapshot,
            "input_hash": record["source_hash"],
            "total_units": len(result["items"]),
            "offset": 0,
            "work_units": 1,
            "published_ids": artifact.get("published_ids", []),
            "skipped_count": 0,
        }
        await run_db(action_item_db.save_progress, key, self.owner, artifact)

    async def _filter_and_publish(self, record: dict, *, deadline: float) -> None:
        key = record["meeting_id"]
        artifact = deepcopy(record["action_items_artifact"])
        _validate_checkpoint(artifact, record)
        candidates = artifact["items"]
        corpus = await run_db(proposal_corpus.snapshot)
        if _grounding_changed(candidates, corpus):
            await run_db(
                action_item_db.save_progress,
                key,
                self.owner,
                {
                    "published_ids": artifact.get("published_ids", []),
                },
            )
            raise ProposalConflictError(
                "Action Item target or project grounding changed; regenerate current candidates"
            )
        dismissed = proposals.dismissed_candidate_indices(
            artifact["input_snapshot"], candidates, corpus
        )
        if not candidates:
            result = {"keep": [], "supersede": [], "decisions": {}}
        else:
            embeddings = await run_db(get_embeddings)
            budget = await run_db(get_memory_token_budget)
            fingerprint = matching.digest(
                {
                    "model": MEMORY_EMBEDDING_MODEL,
                    "dimensions": MEMORY_EMBEDDING_DIMENSION,
                    "tokens": budget.max_tokens,
                    "special_tokens": budget.special_tokens,
                    "versions": {
                        name: version(name)
                        for name in (
                            "sentence-transformers",
                            "transformers",
                            "langchain-huggingface",
                        )
                    },
                    "policy": [
                        matching.POLICY_VERSION,
                        matching.COSINE_FLOOR,
                        matching.LEXICAL_FLOOR,
                    ],
                }
            )
            batch_records = [
                {"key": f"candidate:{index}", "kind": "candidate", "data": item}
                for index, item in enumerate(candidates)
            ]
            records = [*corpus["records"], *batch_records]
            search = await run_db(
                matching.search,
                candidates,
                records,
                embeddings=embeddings,
                budget=budget,
                dimensions=MEMORY_EMBEDDING_DIMENSION,
            )
            cache = artifact.get("filter", {}).get("candidates", {})
            by_key = {item["key"]: item for item in records}
            pending, retained = {}, {}
            for index, item in enumerate(candidates):
                identity = str(index)
                keys = sorted(hit["key"] for hit in search["hits"][identity])
                input_key = matching.digest(
                    [
                        item,
                        fingerprint,
                        {
                            name: matching.comparison_digest(by_key[name])
                            for name in keys
                        },
                        [
                            {"id": project["id"], "name": project["name"]}
                            for project in corpus["projects"]
                        ],
                    ]
                )
                prior = cache.get(identity, {})
                if prior.get("input_key") != input_key:
                    prior = {
                        "input_key": input_key,
                        "covered_keys": [],
                        "results": [],
                        "complete": False,
                    }
                _validate_coverage(
                    prior, item, index, keys, by_key, artifact["input_snapshot"]
                )
                retained[identity] = prior
                if not prior["complete"]:
                    pending[identity] = [
                        hit
                        for hit in search["hits"][identity]
                        if hit["key"] not in prior["covered_keys"]
                    ]
            artifact["phase"] = "filtering"
            artifact["filter"] = {
                "fingerprint": fingerprint,
                "manifest": corpus["manifest"],
                "digest": corpus["digest"],
                "candidates": retained,
                "scored_records": search["scored_records"],
                "encoded_chunks": search["encoded_chunks"],
            }
            if pending:
                windows = action_item_filter.windows(
                    artifact["input_snapshot"],
                    candidates,
                    records,
                    pending,
                    candidate_ids=[int(index) for index in pending],
                )
                for data in windows:

                    async def validate_source():
                        await run_db(action_item_db.assert_current, key, self.owner)

                    outcome = await action_item_filter.analyze_window(
                        artifact["input_snapshot"],
                        data,
                        deadline=deadline,
                        validate_context=validate_source,
                    )
                    decisions = [
                        action_item_filter.FilterDecision.model_validate(item)
                        for item in outcome["items"]
                    ]
                    if error := action_item_filter.validate_decisions(decisions, data):
                        raise ValueError(error)
                    for item in decisions:
                        identity = str(item.candidate_id)
                        previous = retained[identity]
                        previous["results"].append(item.model_dump())
                        previous["covered_keys"] = sorted(
                            set(previous["covered_keys"])
                            | set(action_item_filter.comparison_keys(item))
                        )
                        required = {hit["key"] for hit in search["hits"][identity]}
                        previous["complete"] = set(previous["covered_keys"]) == required
                    artifact["work_units"] = artifact.get("work_units", 1) + 1
                    await run_db(
                        action_item_db.save_progress, key, self.owner, artifact
                    )
            for identity, item in retained.items():
                if not item["complete"]:
                    raise ValueError(
                        "Action Item filter did not cover every relevant comparison"
                    )
            result = action_item_filter.reduce_decisions(
                candidates,
                records,
                [{"items": item["results"]} for item in retained.values()],
                dismissed=dismissed,
            )
        artifact["phase"] = "publishing"
        await run_db(action_item_db.save_progress, key, self.owner, artifact)
        published = await run_db(
            proposals.publish_filtered_batch,
            artifact["input_snapshot"],
            candidates,
            result,
            expected_digest=corpus["digest"],
            artifact=artifact,
            lease_owner=self.owner,
        )
        if published["stale"]:
            if _grounding_changed(candidates, published["corpus"]):
                artifact = {"published_ids": artifact.get("published_ids", [])}
            else:
                artifact["phase"] = "filtering"
            await run_db(action_item_db.save_progress, key, self.owner, artifact)
            raise ProposalConflictError(
                "Action Item corpus changed; recheck affected candidate comparisons"
            )
        self.report.update(
            outcome="done",
            phase="done",
            generated=len(candidates),
            proposals=published["proposals"],
            skipped=published["skipped"],
            superseded=published["superseded"],
        )


def _grounding_changed(candidates: list[dict], corpus: dict) -> bool:
    tasks = {
        record["data"]["id"]: record["data"]
        for record in corpus["records"]
        if record["kind"] == "task"
    }
    projects = {project["name"] for project in corpus["projects"]}
    for raw in candidates:
        item = ActionItemCandidate.model_validate(raw)
        project = item.changes.get("project")
        if project is not None and project not in projects:
            return True
        if item.action == "update" and (
            item.target_id not in tasks
            or tasks[item.target_id]["revision"] != item.expected_revision
        ):
            return True
    return False


def _validate_coverage(
    prior: dict,
    candidate: dict,
    index: int,
    keys: list[str],
    records: dict,
    snapshot: dict,
) -> None:
    if (
        not isinstance(prior.get("covered_keys"), list)
        or len(prior["covered_keys"]) != len(set(prior["covered_keys"]))
        or set(prior["covered_keys"]) - set(keys)
        or type(prior.get("complete")) is not bool
        or not isinstance(prior.get("results"), list)
        or (
            prior["complete"]
            and (set(prior["covered_keys"]) != set(keys) or not prior["results"])
        )
    ):
        raise ValueError("Saved Action Item semantic coverage is invalid")
    covered = set()
    for raw in prior["results"]:
        item = action_item_filter.FilterDecision.model_validate(raw)
        explicit = set(action_item_filter.comparison_keys(item))
        if explicit - set(keys) or explicit & covered:
            raise ValueError("Saved filter decisions have invalid comparison coverage")
        covered.update(explicit)
        data = {
            "candidates": [candidate],
            "meeting_snapshot": snapshot,
            "candidate_ids": [0],
            "comparison_records": [records[key] for key in explicit],
            "comparison_pairs": {"0": sorted(explicit)},
        }
        if item.candidate_id != index:
            raise ValueError("Saved filter decision belongs to another candidate")
        item = item.model_copy(update={"candidate_id": 0})
        if error := action_item_filter.validate_decisions([item], data):
            raise ValueError(error)
    if covered != set(prior["covered_keys"]):
        raise ValueError("Saved filter coverage requires explicit comparison decisions")


def _validate_checkpoint(artifact: dict, record: dict) -> None:
    items, offset = artifact.get("items"), artifact.get("offset")
    snapshot = artifact.get("input_snapshot")
    if (
        artifact.get("version", 1) not in {1, 2}
        or (
            artifact.get("version") == 2
            and artifact.get("phase")
            not in {"generated", "filtering", "publishing", "done"}
        )
        or not isinstance(items, list)
        or (artifact.get("version", 1) == 1 and len(items) > 20)
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

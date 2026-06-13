"""Tools for the improve graph's pragmatic-engineer agent.

Research tools are thin read-only wrappers over existing service functions.
``build_file_proposal_tool`` is the single write path: it validates through
``stage_proposal`` (the LLM trust boundary) and stages into an in-memory
collector — nothing persists until the graph's persist node runs.
"""
from __future__ import annotations

import json

from langchain_core.tools import tool

HARNESS_KINDS = ("rule", "skill", "hook")


def _dumps(value) -> str:
    return json.dumps(value, default=str)


@tool
def search_memories(query: str, limit: int = 10) -> str:
    """Semantically search long-term memories. Returns JSON: id, content, repo, tags, created_at."""
    from services.memory.db import search

    rows = search(query, limit=limit)
    return _dumps(
        [
            {k: row.get(k) for k in ("id", "content", "repo", "tags", "created_at")}
            for row in rows
        ]
    )


@tool
def search_plans(query: str) -> str:
    """Fuzzy-search planning docs by title. Returns JSON: id, title, project, updated_at."""
    from services.api.models.plan import search_plans as _search

    rows = _search(query, limit=25)
    return _dumps([{k: row.get(k) for k in ("id", "title", "project", "updated_at")} for row in rows])


@tool
def get_plan(plan_id: int) -> str:
    """Fetch one planning doc in full (title, body, project) by id."""
    from services.api.models.plan import get_plan as _get

    row = _get(plan_id)
    return _dumps(row) if row else f"No plan with id {plan_id}"


@tool
def list_harness_items(item_type: str) -> str:
    """List harness items of a type ('rule', 'skill', or 'hook'): name, project, agents, enabled."""
    if item_type not in HARNESS_KINDS:
        return f"item_type must be one of {HARNESS_KINDS}"
    from services.api.models.shared.harness import list_items_summary

    rows = list_items_summary(item_type)
    return _dumps(
        [{k: row.get(k) for k in ("name", "project", "agents", "enabled", "version")} for row in rows]
    )


@tool
def get_harness_item(item_type: str, name: str) -> str:
    """Fetch one harness item in full (including its body) by type and name."""
    if item_type not in HARNESS_KINDS:
        return f"item_type must be one of {HARNESS_KINDS}"
    from services.api.models.shared.harness import get_item

    row = get_item(item_type, name)
    if not row:
        return f"No {item_type} named '{name}'"
    return _dumps({k: row.get(k) for k in ("name", "project", "agents", "enabled", "version", "content")})


@tool
def list_background_jobs() -> str:
    """List background jobs: name, description, schedule_config, input_params."""
    from services.jobs.models.job import list_jobs

    rows, _ = list_jobs(limit=200)
    return _dumps(
        [
            {k: row.get(k) for k in ("name", "description", "schedule_config", "input_params", "version")}
            for row in rows
        ]
    )


RESEARCH_TOOLS = [
    search_memories,
    search_plans,
    get_plan,
    list_harness_items,
    get_harness_item,
    list_background_jobs,
]


def build_file_proposal_tool(collector: dict, max_proposals: int):
    """A file_proposal tool bound to this run's collector.

    Validation errors come back as the tool result so the agent can
    self-correct; the collector is keyed by fingerprint so re-filings during
    rubric revision loops stay idempotent.
    """

    @tool
    def file_proposal(
        target_kind: str,
        action: str,
        target_name: str,
        title: str,
        rationale: str,
        evidence: list[dict] | None = None,
        body: str | None = None,
        project: str | None = None,
        schedule_config: dict | None = None,
        input_params: dict | None = None,
        description: str | None = None,
    ) -> str:
        """File one improvement proposal for user review.

        target_kind: 'rule' | 'skill' | 'hook' | 'job'. action: 'create' | 'update'.
        For rule/skill/hook provide the FULL proposed markdown `body` (for updates,
        the complete new body, not a diff). For jobs provide `schedule_config` /
        `input_params` / `description` (all for create; the changed ones for update).
        evidence: [{"source": "plan"|"memory", "id": "...", "note": "..."}] citing the
        plans/memories that motivated this. Returns a confirmation or the specific
        validation error to fix.
        """
        from services.proposals.service import stage_proposal

        if len(collector) >= max_proposals:
            return f"Proposal limit reached ({max_proposals}); do not file more this run."
        try:
            staged = stage_proposal(
                {
                    "target_kind": target_kind,
                    "action": action,
                    "target_name": target_name,
                    "title": title,
                    "rationale": rationale,
                    "evidence": evidence or [],
                    "body": body,
                    "project": project,
                    "schedule_config": schedule_config,
                    "input_params": input_params,
                    "description": description,
                }
            )
        except ValueError as exc:  # includes DuplicateProposalError
            return f"Proposal rejected: {exc}"
        collector[staged["fingerprint"]] = staged
        return f"Staged proposal '{title}' ({action} {target_kind} '{target_name}')."

    return file_proposal

"""Execution-time device/repo scoping for background jobs.

Mirrors the harness deployment-config resolution
(services/api/models/shared/sync.py:resolve_sync_targets) — additive configs
minus subtractive (exclude) configs, filtered by device — but without the
per-agent dimension, since jobs are scripts, not per-agent harness items.

Scoping is an execution-time concern: the scheduler asks "should this job run
on THIS device?" Jobs are never written to agent config files, so this never
touches the sync flow.
"""
from __future__ import annotations

# Reuse the harness device-match rule rather than re-implementing it (DRY).
from services.api.models.shared.sync import _device_matches
from services.jobs.models.config import list_configs


def resolve_job_targets(job_id: int, device_name: str) -> list[str]:
    """Repos this job should run on for ``device_name``.

    An empty list means the job does not run on this device (no enabled
    additive config matches, or every match is excluded).
    """
    configs = list_configs(job_id)
    relevant = [
        c for c in configs
        if c["enabled"] and _device_matches(c["device"], device_name)
    ]

    additive = [c for c in relevant if not c["exclude"]]
    if not additive:
        return []

    targets = {c["repo"] for c in additive}
    for c in relevant:
        if c["exclude"]:
            targets.discard(c["repo"])

    return sorted(targets)


def job_runs_on_device(job_id: int, device_name: str) -> bool:
    """Whether the job has at least one in-scope target on this device."""
    return bool(resolve_job_targets(job_id, device_name))

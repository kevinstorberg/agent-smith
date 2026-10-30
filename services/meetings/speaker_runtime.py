from __future__ import annotations

from services.meetings import speaker_analysis, speaker_context, speaker_db, speaker_profiles
from services.meetings.service import run_db


async def identify(run, record: dict, *, deadline: float) -> None:
    from services.graphs.model_config import resolve_model_id

    meeting_id, content_hash = record["meeting_id"], record["transcript_hash"]
    current, artifact = await run_db(speaker_db.prepare, meeting_id, run.owner, content_hash)
    segments = current["transcript"]["segments"]
    artifact.update(total_units=len(segments), model=resolve_model_id("meeting_speaker", "curator"), prompt_version=2)
    from services.meetings import profile_directory

    directory = await run_db(profile_directory.names, limit=100)
    artifact["canonical_candidates"] = speaker_profiles.directory_candidates(directory["items"])
    snapshot = speaker_db.context_snapshot(current, manual=current.get("manual_context", artifact["manual_snapshot"]))
    attached = await run_db(speaker_profiles.attached_candidates, snapshot)
    snapshot["identity_candidates"] = [*artifact.get("resolved_candidates", []), *attached, *artifact["canonical_candidates"]]
    await run_db(speaker_db.save_progress, meeting_id, run.owner, content_hash, artifact)

    async def validate_context(expected_profiles: dict) -> dict:
        return await run_db(speaker_db.validate_context, meeting_id, run.owner, content_hash, artifact, expected_profiles)

    while artifact["offset"] < len(segments):
        offset = artifact["offset"]
        targets, end = speaker_analysis.target_window(segments, offset)
        if targets:
            context, anchors = speaker_context.window_context(snapshot, segments, offset, artifact["draft_assignments"])
            data = speaker_context.quoted_context(snapshot, targets, context, anchors)
            result = await speaker_analysis.identify_statements(snapshot, targets, context=context, anchors=anchors, deadline=deadline,
                                                                validate_context=validate_context)
            discovered = result.get("resolved_candidates", [])
            validated = speaker_analysis.validate_assignments(result["assignments"], targets, data["read_only_context"],
                                                              [*data["candidates"], *discovered], data["read_only_identity_anchors"])
            artifact.setdefault("profile_revisions", {}).update(result.get("profile_revisions", {}))
            used_ids = {item["profile_id"] for item in validated if item.get("profile_id")}
            previous = artifact.setdefault("resolved_candidates", [])
            for person in discovered:
                if person["profile_id"] in used_ids and person not in previous:
                    previous.append(person)
            snapshot["identity_candidates"] = [*previous, *attached, *artifact["canonical_candidates"]]
            artifact["draft_assignments"].extend(validated)
            artifact["reason"] = result.get("reason", "")
        artifact["offset"] = end
        await run_db(speaker_db.save_progress, meeting_id, run.owner, content_hash, artifact)
    changed = await run_db(speaker_db.apply, meeting_id, run.owner, content_hash, artifact)
    record.update(speaker_status="done")
    run.speaker_report.update(outcome="done", changed=changed)

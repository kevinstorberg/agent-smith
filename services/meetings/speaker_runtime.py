from __future__ import annotations

from services.meetings import speaker_analysis, speaker_db
from services.meetings.service import run_db


async def identify(run, record: dict, *, deadline: float) -> None:
    from services.graphs.model_config import resolve_model_id

    meeting_id, content_hash = record["meeting_id"], record["transcript_hash"]
    current, artifact = await run_db(speaker_db.prepare, meeting_id, run.owner, content_hash)
    segments = current["transcript"]["segments"]
    artifact.update(total_units=len(segments), model=resolve_model_id("meeting_speaker", "curator"), prompt_version=1)
    if "canonical_candidates" not in artifact:
        from services.meetings import profile_directory

        directory = await run_db(profile_directory.names, limit=100)
        artifact["canonical_candidates"] = [
            {"name": name, "profile_id": person["id"], **({"email": email} if email else {})}
            for person in directory["items"] for name in [person["display_name"], *person.get("nicknames", [])]
            for email in (person.get("emails") or [None])
        ][:200]
    snapshot = speaker_db.context_snapshot(current, manual=artifact["manual_snapshot"])
    snapshot["identity_candidates"] = [*artifact.get("resolved_candidates", []), *artifact["canonical_candidates"]]
    await run_db(speaker_db.save_progress, meeting_id, run.owner, content_hash, artifact)
    while artifact["offset"] < len(segments):
        offset = artifact["offset"]
        targets, end = speaker_analysis.target_window(segments, offset)
        if targets:
            context = [{**segment, "text": segment["text"][:1000]} for segment in segments[max(0, offset - 3):offset]]
            anchors = [{key: assignment.get(key) for key in ("segment_id", "name", "email", "profile_id", "rationale")}
                       for assignment in artifact["draft_assignments"] if assignment["confidence"] == "high"][-12:]
            result = await speaker_analysis.identify_statements(snapshot, targets, context=context, anchors=anchors, deadline=deadline)
            discovered = result.get("resolved_candidates", [])
            validated = speaker_analysis.validate_assignments(result["assignments"], targets, context,
                                                              [*speaker_analysis.candidates(snapshot), *discovered], anchors)
            used_ids = {item["profile_id"] for item in validated if item.get("profile_id")}
            previous = artifact.setdefault("resolved_candidates", [])
            for person in discovered:
                if person["profile_id"] in used_ids and person not in previous:
                    previous.append(person)
            snapshot["identity_candidates"] = [*previous, *artifact["canonical_candidates"]]
            artifact["draft_assignments"].extend(validated)
            artifact["reason"] = result.get("reason", "")
        artifact["offset"] = end
        await run_db(speaker_db.save_progress, meeting_id, run.owner, content_hash, artifact)
    changed = await run_db(speaker_db.apply, meeting_id, run.owner, content_hash, artifact)
    record.update(speaker_status="done")
    run.speaker_report.update(outcome="done", changed=changed)

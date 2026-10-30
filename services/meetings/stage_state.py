from __future__ import annotations


def stage_name(stage: str) -> str:
    if stage not in {"memory", "profile", "speaker"}:
        raise ValueError("Unknown meeting stage")
    return stage


def progress(row: dict | None, stage: str, *, total_units: int | None = None) -> dict:
    stage = stage_name(stage)
    row = row or {}
    if row.get(stage + "_progress") is not None:
        return {**row[stage + "_progress"], "next_attempt_at": row.get(stage + "_next_attempt_at")}
    artifact = row.get(stage + "_artifact") or {}
    return {
        "processed_units": artifact.get("offset", 0), "total_units": artifact.get("total_units", total_units),
        "staged_count": len(artifact.get("draft_assignments", [])) if stage == "speaker" else len(artifact.get("items", [])) + (len(artifact.get("metadata_updates", [])) if stage == "profile" else 0),
        "saved_count": sum(item.get("confidence") == "high" for item in artifact.get("assignments", [])) if stage == "speaker"
        else len(artifact.get("published_ids" if stage == "memory" else "profile_ids", [])),
        "attempts": row.get(stage + "_attempts") or 0, "next_attempt_at": row.get(stage + "_next_attempt_at"),
    }


def transcript(row: dict) -> dict:
    status = row.get("transcript_status") or "not_imported"
    return {"status": "capturing" if status == "pending" and row.get("memory_running", row.get("running")) else status,
            "total": row.get("total", 0) if status == "ready" else 0,
            "error_type": row.get("error_type") if status != "not_imported" else None,
            "captured_at": row.get("captured_at") if status != "not_imported" else None}


def generation(row: dict, stage: str) -> dict:
    if stage not in {"memory", "profile"}:
        raise ValueError("Generation stage must be memory or profile")
    status, reason = row.get(stage + "_status") or "not_imported", None
    if status == "done":
        reason = row.get(stage + "_reason", (row.get(stage + "_artifact") or {}).get("reason"))
    elif status != "not_imported":
        if row.get("transcript_status") != "ready":
            status, reason = "blocked", "transcript_" + row["transcript_status"]
        elif row.get("memory_running" if stage == "memory" else "persona_running", row.get("running")):
            status = "running"
    return {"status": status, "reason": reason, "error_type": row.get(stage + "_error"),
            "progress": progress(row, stage, total_units=row.get("total_units"))}


def speakers(row: dict) -> dict:
    status = row.get("speaker_status") or "not_imported"
    return {"status": "running" if status == "pending" and row.get("memory_running") else status,
            "error_type": row.get("speaker_error"), "progress": progress(row, "speaker")}


def edit_lock(row: dict) -> str | None:
    if row.get("persona_running"):
        return "analyzing_personas"
    if row.get("memory_running"):
        if row.get("transcript_status") == "pending":
            return "capturing_transcript"
        if row.get("speaker_status") == "pending":
            return "identifying_participants"
    return None

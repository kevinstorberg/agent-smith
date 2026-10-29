from __future__ import annotations

from copy import deepcopy

from services.meetings import profile_fields


def source_ids(rows: list[dict]) -> set[str]:
    return {source["meeting_id"] for profile in rows for snapshot in _snapshots(profile)
            for source in snapshot.get("metadata_provenance", {}).values()
            if isinstance(source, dict) and source.get("meeting_id")}


def _snapshots(row: dict):
    yield row
    for entry in row.get("merge_history", []):
        for key in ("previous_source", "previous_target"):
            if isinstance(entry.get(key), dict):
                yield from _snapshots(entry[key])


def human(field: str, metadata: dict, provenance: dict) -> bool:
    source = provenance.get(field)
    return source.get("human") is True if isinstance(source, dict) else field in metadata


def source_valid(source: dict, contexts: dict[str, dict]) -> bool:
    context = contexts.get(source.get("meeting_id"))
    return bool(context and context["available"] and context["transcript_status"] == "ready"
                and context["transcript_hash"] == source.get("transcript_hash")
                and context["participants_revision"] == source.get("participants_revision"))


def claim_source_valid(claim: dict, contexts: dict[str, dict]) -> bool:
    source = {**claim, "participants_revision": claim.get("participants_revision", 0)}
    return source_valid(source, contexts)


def visible(row: dict, contexts: dict[str, dict]) -> tuple[dict, dict]:
    metadata, provenance = row.get("metadata", {}), row.get("metadata_provenance", {})
    fields, sources = {}, {}
    for field in profile_fields.METADATA_FIELDS:
        source = provenance.get(field, {})
        if human(field, metadata, provenance):
            sources[field] = {"human": True}
            if field in metadata:
                fields[field] = metadata[field]
        elif field in metadata and source_valid(source, contexts):
            fields[field], sources[field] = metadata[field], deepcopy(source)
    return fields, sources


def project(row: dict, contexts: dict[str, dict]) -> dict:
    metadata, provenance = visible(row, contexts)
    result = {**row, "metadata": metadata, "metadata_provenance": provenance}
    if "merge_history" in row:
        result["merge_history"] = [
            {**entry, **{key: project(entry[key], contexts) for key in ("previous_source", "previous_target")
                         if isinstance(entry.get(key), dict)}} for entry in row["merge_history"]
        ]
    return result


def human_patch(row: dict, changes: dict) -> tuple[dict, dict]:
    metadata = profile_fields.patch(row.get("metadata", {}), changes)
    provenance = deepcopy(row.get("metadata_provenance", {}))
    provenance.update({field: {"human": True} for field in changes})
    return metadata, provenance


def fill_missing(row: dict, patches: list[dict], record: dict, contexts: dict[str, dict]) -> tuple[dict, dict]:
    metadata, provenance = deepcopy(row.get("metadata", {})), deepcopy(row.get("metadata_provenance", {}))
    current, _ = visible(row, contexts)
    for patch in patches:
        for field, value in patch["fields"].items():
            if field in current or human(field, metadata, provenance):
                continue
            metadata[field] = current[field] = value
            provenance[field] = {
                "meeting_id": str(record["meeting_id"]), "transcript_hash": record["transcript_hash"],
                "participants_revision": record.get("participants_revision", 0),
                "evidence": deepcopy(patch["evidence"]),
            }
    return metadata, provenance


def rebase_attribution(row: dict, meeting_id: str, revision: int, contexts: dict, mappings: list[dict]) -> dict:
    provenance = deepcopy(row.get("metadata_provenance", {}))
    for source in provenance.values():
        if (source.get("meeting_id") == meeting_id and source_valid(source, contexts) and source.get("evidence")
                and all(mapping.get(evidence["segment_id"]) == str(row["id"])
                        for mapping in mappings for evidence in source["evidence"])):
            source["participants_revision"] = revision
    return provenance


def merge(source: dict, target: dict, contexts: dict[str, dict]) -> tuple[dict, dict]:
    source_visible, _ = visible(source, contexts)
    target_visible, _ = visible(target, contexts)
    metadata, provenance = {}, {}
    for field in profile_fields.METADATA_FIELDS:
        chosen = None
        for row in (target, source):
            if human(field, row.get("metadata", {}), row.get("metadata_provenance", {})):
                chosen = row
                break
        if chosen is not None:
            provenance[field] = {"human": True}
            if field in chosen.get("metadata", {}):
                metadata[field] = chosen["metadata"][field]
        else:
            chosen = target if field in target_visible else source if field in source_visible else None
            if chosen is not None:
                metadata[field] = chosen["metadata"][field]
                provenance[field] = deepcopy(chosen["metadata_provenance"][field])
    return metadata, provenance


def source_sql(source: str, *, legacy_claim: bool = False) -> str:
    participants_revision = f"{source}->>'participants_revision'"
    if legacy_claim:
        participants_revision = f"(CASE WHEN {source} ? 'participants_revision' THEN {participants_revision} ELSE '0' END)"
    return f"""EXISTS (SELECT 1 FROM meeting_summaries metadata_source
        JOIN meeting_digestions metadata_context ON metadata_context.meeting_id = metadata_source.id
        WHERE metadata_source.id::text = {source}->>'meeting_id'
          AND metadata_source.available AND metadata_context.transcript_status = 'ready'
          AND metadata_context.transcript_hash = {source}->>'transcript_hash'
          AND metadata_source.participants_revision::text = {participants_revision})"""


def visible_sql(alias: str) -> str:
    return f"""(SELECT coalesce(jsonb_object_agg(field.key, field.value), '{{}}'::jsonb)
        FROM jsonb_each({alias}.metadata) field
        WHERE NOT ({alias}.metadata_provenance ? field.key)
           OR {alias}.metadata_provenance->field.key->>'human' = 'true'
           OR {source_sql(f'{alias}.metadata_provenance->field.key')})"""

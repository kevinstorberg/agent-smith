from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from services.meetings import profile_fields, profile_metadata


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def claim_signature(claim: dict) -> str:
    return digest({key: claim.get(key) for key in (
        "id", "subject_id", "target_id", "category", "content", "status", "correction",
        "meeting_id", "transcript_hash", "participants_revision", "evidence", "superseded",
    )})


def effective_claims(row: dict, contexts: dict[str, dict]) -> list[dict]:
    claims = []
    for claim in row.get("claims", []):
        if (claim.get("superseded") or claim.get("status") == "rejected"
                or not profile_metadata.claim_source_valid(claim, contexts)):
            continue
        content = (claim.get("correction") or {}).get("content") if claim.get("status") == "corrected" else claim.get("content")
        if content:
            claims.append({**claim, "effective_content": content, "signature": claim_signature(claim)})
    return claims


def coverage(claims: list[dict]) -> dict:
    return {"claim_count": len(claims), "meeting_count": len({claim["meeting_id"] for claim in claims})}


def human(section: str, row: dict) -> bool:
    proof = row.get("section_evidence", {}).get(section)
    return proof.get("human") is True if isinstance(proof, dict) else section in row.get("section_notes", {})


def human_patch(row: dict, changes: dict | None, release: list[str]) -> tuple[dict, dict]:
    notes = profile_fields.patch(row.get("section_notes", {}), changes or {})
    proofs = deepcopy(row.get("section_evidence", {}))
    for section in changes or {}:
        proofs[section] = {"human": True, "origin": "human"}
    for section in release:
        if section in (changes or {}):
            raise ValueError("A section cannot be edited and released in the same request")
        proofs[section] = {**proofs.get(section, {}), "human": False}
        if "claim_ids" not in proofs[section]:
            proofs[section]["origin"] = "human"
    return notes, proofs


def input_hash(row: dict, claims: list[dict]) -> str:
    # Agent-authored narratives are outputs, so publishing them must not dirty their own inputs.
    return digest({
        "prompt_version": 2, "identity": {key: row.get(key) for key in ("id", "display_name", "email", "nicknames")},
        "metadata": row.get("metadata", {}), "metadata_provenance": row.get("metadata_provenance", {}),
        "claims": sorted((claim["id"], claim["signature"]) for claim in claims),
        "human_sections": {key: row.get("section_notes", {}).get(key) for key in profile_fields.SECTION_FIELDS if human(key, row)},
        "relationships": [{key: edge.get(key) for key in ("id", "revision", "subject_id", "target_id", "label", "notes", "dismissed")}
                          for edge in row.get("relationships", [])],
    })


def proof_valid(proof: dict, claims: list[dict], contexts: dict[str, dict]) -> bool:
    current = {claim["id"]: claim["signature"] for claim in claims}
    ids = proof.get("claim_ids", [])
    signatures = proof.get("claim_signatures", {})
    return bool(ids and all(current.get(key) == signatures.get(key) for key in ids)
                and all(profile_metadata.source_valid(source, contexts) for source in proof.get("sources", [])))


def project(row: dict, claims: list[dict], contexts: dict[str, dict]) -> dict:
    notes, proofs = {}, {}
    for section in profile_fields.SECTION_FIELDS:
        proof = row.get("section_evidence", {}).get(section, {})
        if human(section, row) or proof.get("origin") == "human" or proof_valid(proof, claims, contexts):
            if section in row.get("section_notes", {}):
                notes[section] = row["section_notes"][section]
            proofs[section] = deepcopy(proof) if proof else {"human": True}
        elif proof.get("status") == "insufficient_evidence":
            proofs[section] = {"human": False, "status": "insufficient_evidence", "coverage": coverage(claims)}
    result = {**row, "section_notes": notes, "section_evidence": proofs}
    if "merge_history" in row:
        result["merge_history"] = [
            {**entry, **{key: project(entry[key], claims, contexts) for key in ("previous_source", "previous_target")
                         if isinstance(entry.get(key), dict)}} for entry in row["merge_history"]
        ]
    return result


def source_ids(rows: list[dict]) -> set[str]:
    ids = set()
    for row in rows:
        for proof in row.get("section_evidence", {}).values():
            ids.update(source["meeting_id"] for source in proof.get("sources", []) if source.get("meeting_id"))
        for entry in row.get("merge_history", []):
            ids.update(source_ids([entry[key] for key in ("previous_source", "previous_target") if isinstance(entry.get(key), dict)]))
    return ids


def rebase_attribution(row: dict, claims: list[dict], before: dict, after: dict, meeting_id: str, revision: int) -> dict:
    proofs = deepcopy(row.get("section_evidence", {}))
    old = effective_claims(row, before)
    current = {claim["id"]: claim for claim in effective_claims({**row, "claims": claims}, after)}
    for proof in proofs.values():
        if (any(source.get("meeting_id") == meeting_id for source in proof.get("sources", []))
                and proof_valid(proof, old, before) and all(key in current for key in proof.get("claim_ids", []))):
            proof["claim_signatures"] = {key: current[key]["signature"] for key in proof["claim_ids"]}
            for source in proof["sources"]:
                if source.get("meeting_id") == meeting_id:
                    source["participants_revision"] = revision
    return proofs

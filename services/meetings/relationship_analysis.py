from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from services.personas import sections


def human(edge: dict) -> bool:
    proof = edge.get("analysis_evidence") or {}
    return proof.get("human", edge.get("human_confirmed", False)) is True


def valid(edge: dict, claims: list[dict], contexts: dict) -> bool:
    proof = edge.get("analysis_evidence") or {}
    if proof.get("origin") == "legacy":
        return (str(edge["subject_id"]) == proof.get("subject_id")
                and (str(edge["target_id"]) if edge.get("target_id") else None) == proof.get("target_id")
                and sections.proof_valid(proof, claims, contexts))
    return (str(edge["subject_id"]) == proof.get("subject_id") and str(edge["target_id"]) == proof.get("target_id")
            and all(claim.get("canonical_target_id", claim.get("target_id")) == str(edge["target_id"])
                    for claim in claims if claim["id"] in proof.get("claim_ids", []))
            and sections.proof_valid(proof, claims, contexts))


def project(edge: dict, claims: list[dict], contexts: dict, *, full_proof: bool = False) -> dict:
    proof = deepcopy(edge.get("analysis_evidence") or {"human": human(edge)})
    protected = human(edge)
    supported = valid(edge, claims, contexts)
    chosen = [claim for claim in claims if claim["id"] in proof.get("claim_ids", [])] if supported else []
    summary = {"human": protected, "status": proof.get("status", "insufficient_evidence"),
               "claim_count": len(chosen), "coverage": sections.coverage(chosen), "generated_at": proof.get("generated_at")}
    if proof.get("origin"):
        summary["origin"] = proof["origin"]
    if not protected and proof.get("status") == "supported" and not supported:
        summary["status"] = "stale"
    return {**edge, "notes": edge.get("notes", "") if protected or supported or proof.get("origin") == "human" else "",
            "analysis_evidence": proof if full_proof else summary,
            "analysis_stale": not protected and proof.get("status") == "supported" and not supported}


def proof(edge: dict, item: dict, claims: list[dict], contexts: dict) -> dict:
    chosen = [claim for claim in claims if claim["id"] in item["claim_ids"]]
    return {"version": 1, "human": False, "status": item["status"],
            "subject_id": str(edge["subject_id"]), "target_id": str(edge["target_id"]),
            "claim_ids": item["claim_ids"], "claim_signatures": {claim["id"]: claim["signature"] for claim in chosen},
            "sources": [{"meeting_id": key, "transcript_hash": contexts[key]["transcript_hash"],
                         "participants_revision": contexts[key]["participants_revision"]}
                        for key in sorted({claim["meeting_id"] for claim in chosen})],
            "generated_at": datetime.now(timezone.utc).isoformat()}


def inputs(edges: list[dict]) -> list[dict]:
    return [{"id": str(edge["id"]), "subject_id": str(edge["subject_id"]), "target_id": str(edge["target_id"]),
             "dismissed": edge.get("dismissed", False), "label": edge.get("label", ""),
             "human": human(edge), "human_notes": edge.get("notes", "") if human(edge) else None}
            for edge in sorted(edges, key=lambda item: str(item["id"]))]

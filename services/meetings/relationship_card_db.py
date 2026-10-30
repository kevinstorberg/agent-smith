from __future__ import annotations

from copy import deepcopy
from uuid import UUID

from psycopg2.extras import Json

from services.meetings import profile_db, profile_fields, relationship_cards, relationship_db
from services.personas import sections


def _load(cur, row: dict, visible: dict | None = None) -> dict:
    visible = visible if visible is not None else profile_db._visible(cur, [row])[0]
    edges = relationship_db.for_profiles(cur, [row], include_dismissed=True, include_unavailable=True,
                                         include_evidence=False, include_card_state=True)[str(row["id"])]
    endpoints = {str(edge["target_id"]) if str(edge["subject_id"]) == str(row["id"]) else str(edge["subject_id"])
                 for edge in edges if edge.get("target_id")}
    cur.execute("""SELECT p.id::text,p.display_name,p.nicknames,
        ARRAY(SELECT a.display_name FROM participant_profiles a WHERE a.merged_into=p.id) AS aliases
        FROM participant_profiles p WHERE NOT p.deleted AND p.merged_into IS NULL ORDER BY p.id""")
    identities = [{**dict(person), "endpoint": person["id"] in endpoints} for person in cur.fetchall()]
    visible = {**visible, "_card_owner_ids": profile_db.canonical_identity_ids(cur, str(row["id"]))}
    cur.execute("SELECT history FROM profile_relationships WHERE subject_id=%s OR target_id=%s ORDER BY id", (row["id"], row["id"]))
    history = [entry for edge in cur.fetchall() for entry in edge["history"]]
    result = relationship_cards.project(visible, edges, identities, raw_owner=row, receipt_history=history)
    return {**result, "_edges": edges}


def for_profile(cur, row: dict, visible: dict) -> dict:
    result = _load(cur, row, visible)
    return {key: result[key] for key in ("relationship_cards", "relationship_unassigned")}


def _fence_sources(cur, row: dict) -> None:
    cur.execute("SELECT analysis_evidence FROM profile_relationships WHERE subject_id=%s OR target_id=%s", (row["id"], row["id"]))
    proofs = [edge["analysis_evidence"] for edge in cur.fetchall()]
    ids = sections.source_ids([row]) | {claim["meeting_id"] for claim in row.get("claims", []) if claim.get("meeting_id")}
    ids.update(source["meeting_id"] for proof in proofs for source in proof.get("sources", []) if source.get("meeting_id"))
    if ids:
        cur.execute("""SELECT m.id FROM meeting_summaries m JOIN meeting_digestions d ON d.meeting_id=m.id
            WHERE m.id IN %s ORDER BY m.id FOR SHARE OF m,d""", (tuple(sorted(ids)),))


def _owner(cur, profile_id: str) -> dict:
    row = profile_db._canonical(cur, str(UUID(profile_id)), lock=True)
    if row is None or row["deleted"]:
        raise ValueError("Participant profile does not exist")
    _fence_sources(cur, row)
    return row


def _target(cur, owner: dict, target_id: str | None, target_revision: int | None, name: str) -> tuple[str | None, str]:
    name = profile_fields.text(name, "Relationship name", 200)
    if target_id is None:
        if not name:
            raise ValueError("Relationship name must be nonblank when no profile is selected")
        return None, name
    if target_revision is None:
        raise ValueError("Target profile revision is required when selecting a profile")
    profile_db._expected_revision(target_revision)
    target = profile_db._editable(cur, str(UUID(target_id)), target_revision)
    if str(target["id"]) == str(owner["id"]):
        raise ValueError("A relationship must connect two different people")
    return str(target["id"]), target["display_name"]


def _raw_edge(cur, edge_id: str) -> dict:
    cur.execute("SELECT * FROM profile_relationships WHERE id=%s FOR UPDATE", (edge_id,))
    row = cur.fetchone()
    if row is None:
        raise profile_db.ProfileRevisionConflict("Relationship changed; reload before editing")
    return dict(row)


def _outgoing(cur, owner_id: str, target_id: str | None, name: str) -> dict | None:
    cur.execute("""SELECT * FROM profile_relationships WHERE subject_id=%s AND target_id IS NOT DISTINCT FROM %s
        AND (%s IS NOT NULL OR lower(target_name)=lower(%s)) ORDER BY dismissed,id FOR UPDATE""",
                (owner_id, target_id, target_id, name))
    row = cur.fetchone()
    return dict(row) if row else None


def _receipt(owner: dict, internal: dict | None = None, *, unassigned_key: str | None = None) -> dict:
    keys = [part["key"] for part in (internal or {}).get("parts", [])]
    if (internal or {}).get("global_clear"):
        keys.append(relationship_cards.digest([str(owner["id"]), "global_clear"]))
    if unassigned_key:
        keys.append(unassigned_key)
    if not keys:
        keys.append(relationship_cards.digest(["card", (internal or {}).get("card", {}).get("id")]))
    return {"action": "legacy_import", "profile_id": str(owner["id"]), "keys": sorted(set(keys)),
            "legacy_state": relationship_cards.legacy_state(owner)}


def _copied_proof(owner: dict, internal: dict | None, target_id: str | None) -> dict:
    selected = (internal or {}).get("selected")
    if selected:
        proof = deepcopy(selected.get("raw_analysis_evidence") or selected.get("analysis_evidence") or {})
        source_id = proof.get("legacy_profile_id", str(selected["subject_id"]))
    else:
        proof = deepcopy(owner.get("section_evidence", {}).get("relationships", {}))
        source_id = str(owner["id"])
    if proof.get("human") is True or proof.get("origin") == "human":
        return {"version": 1, "human": proof.get("human") is True, "origin": "human"}
    if proof.get("claim_ids"):
        return {**proof, "version": 1, "human": False, "origin": "legacy", "legacy_profile_id": source_id,
                "subject_id": str(owner["id"]), "target_id": target_id}
    return {**proof, "version": 1, "human": False, "status": proof.get("status", "insufficient_evidence")}


def _write(cur, owner: dict, edge: dict | None, *, target_id: str | None, name: str,
           label: str, notes: str, proof: dict, receipts: list[dict], dismissed: bool = False) -> dict:
    if edge:
        return relationship_db.edit_in_transaction(cur, edge, target_id=target_id, target_name=name,
            label=label, notes=notes, proof=proof, receipts=receipts, dismissed=dismissed)
    relationship_db._validate_history(receipts)
    cur.execute("""INSERT INTO profile_relationships(subject_id,target_id,target_name,label,notes,analysis_evidence,history,human_confirmed,dismissed)
        VALUES(%s,%s,%s,%s,%s,%s,%s,true,%s) RETURNING *""",
                (owner["id"], target_id, name, label, notes, Json(proof), Json(receipts), dismissed))
    updated = dict(cur.fetchone())
    relationship_db._touch_profiles(cur, (owner["id"], target_id), None, updated)
    return updated


def _result(cur, owner_id: str) -> dict:
    return profile_db._detail(cur, profile_db._canonical(cur, owner_id), include_evidence=False)


def create(profile_id: str, expected_revision: int, name: str, *, profile_id_target: str | None = None,
           target_revision: int | None = None, notes: str | None = None, label: str = "",
           assignment_version: str | None = None) -> dict:
    profile_db._expected_revision(expected_revision)
    label = profile_fields.text(label, "Relationship label", 200)
    if notes is not None:
        notes = profile_fields.text(notes, "Relationship notes")
    with profile_db.profile_write_cursor() as cur:
        owner = _owner(cur, profile_id)
        if owner["revision"] != expected_revision:
            raise profile_db.ProfileRevisionConflict("Profile changed; reload before adding a relationship")
        data = _load(cur, owner)
        target_id, name = _target(cur, owner, profile_id_target, target_revision, name)
        key = relationship_cards.person_key(name, target_id)
        if key in data["_cards"]:
            raise profile_db.ProfileRevisionConflict("This person already has a relationship; edit that card instead")
        receipts = [_receipt(owner)]
        if assignment_version is not None:
            unassigned = data["relationship_unassigned"]
            if not unassigned or unassigned["version"] != assignment_version:
                raise profile_db.ProfileRevisionConflict("Saved analysis changed or is unavailable; reload before assigning it")
            receipts = [_receipt(owner, unassigned_key=data["_unassigned_key"])]
            saved_notes = unassigned["notes"] if notes is None else notes
            proof = _copied_proof(owner, None, target_id) if notes is None else {"version": 1, "human": True}
        else:
            saved_notes = notes or ""
            proof = {"version": 1, "human": notes is not None}
        edge = _outgoing(cur, str(owner["id"]), target_id, name)
        if edge and not edge["dismissed"]:
            raise profile_db.ProfileRevisionConflict("This person already has a relationship; reload before editing")
        _write(cur, owner, edge, target_id=target_id, name=name, label=label, notes=saved_notes, proof=proof, receipts=receipts)
        return _result(cur, str(owner["id"]))


def _card(cur, owner: dict, card_id: str, version: str) -> tuple[dict, dict]:
    if not isinstance(version, str) or len(version) != 64 or any(char not in "0123456789abcdef" for char in version):
        raise ValueError("Relationship version must be a valid snapshot token")
    data = _load(cur, owner)
    internal = data["_cards"].get(card_id)
    if internal is None or internal["card"]["version"] != version:
        raise profile_db.ProfileRevisionConflict("Relationship or its source changed; reload before editing")
    return data, internal


def update(profile_id: str, card_id: str, version: str, *, notes: str | None = None,
           label: str | None = None, name: str | None = None, profile_id_target=Ellipsis,
           target_revision: int | None = None, allow_agent_notes: bool = False) -> dict:
    if type(allow_agent_notes) is not bool or allow_agent_notes and notes is not None:
        raise ValueError("Relationship notes cannot be edited and released together")
    if all(value is None for value in (notes, label, name)) and profile_id_target is Ellipsis and not allow_agent_notes:
        raise ValueError("Provide relationship fields or release automatic updates")
    if notes is not None:
        notes = profile_fields.text(notes, "Relationship notes")
    if label is not None:
        label = profile_fields.text(label, "Relationship label", 200)
    with profile_db.profile_write_cursor() as cur:
        owner = _owner(cur, profile_id)
        data, internal = _card(cur, owner, card_id, version)
        current = internal["card"]
        target_id = current["profile_id"]
        target_name = name if name is not None else current["name"]
        if profile_id_target is not Ellipsis:
            target_id, target_name = _target(cur, owner, profile_id_target, target_revision, target_name)
        elif target_id is None:
            target_id, target_name = _target(cur, owner, None, None, target_name)
        elif name is not None and profile_fields.normalized_text(name) != profile_fields.normalized_text(current["name"]):
            raise ValueError("Rename the linked profile, or unlink it before changing the relationship name")
        key = relationship_cards.person_key(target_name, target_id)
        original_outgoing = next((edge for edge in internal["edges"] if edge["subject_id"] == str(owner["id"])), None)
        original = _raw_edge(cur, original_outgoing["id"]) if original_outgoing else None
        destination = _outgoing(cur, str(owner["id"]), target_id, target_name)
        if target_id is None and destination and not destination["dismissed"] and (original is None or str(original["id"]) != str(destination["id"])):
            raise profile_db.ProfileRevisionConflict("This name already has a relationship; edit that card instead")
        receipts = [_receipt(owner, internal)]
        if original and destination and str(original["id"]) != str(destination["id"]):
            receipts += deepcopy(original["history"])
            receipts.append({"action": "card_link", "before": relationship_db.history_snapshot(cur, original)})
            relationship_db.edit_in_transaction(cur, original, label=original["label"], notes=original["notes"],
                proof=original["analysis_evidence"], dismissed=True)
        elif original:
            destination = original
        if key != card_id and key in data["_cards"]:
            receipts.append({"action": "card_link", "before": deepcopy(data["_cards"][key]["card"])})
        if key != card_id:
            for other in internal["edges"]:
                if str(other["subject_id"]) != str(owner["id"]):
                    raw = _raw_edge(cur, other["id"])
                    relationship_db.edit_in_transaction(cur, raw, label=raw["label"], notes=raw["notes"],
                        proof=raw["analysis_evidence"], dismissed=True)
        proof = {"version": 1, "human": True} if notes is not None else _copied_proof(owner, internal, target_id)
        if allow_agent_notes:
            proof = {**proof, "human": False}
            if proof.get("origin") == "human":
                proof = {"version": 1, "human": False, "origin": "human"}
        _write(cur, owner, destination, target_id=target_id, name=target_name,
               label=current["label"] if label is None else label, notes=current["notes"] if notes is None else notes,
               proof=proof, receipts=receipts)
        return _result(cur, str(owner["id"]))


def delete(profile_id: str, card_id: str, version: str) -> None:
    with profile_db.profile_write_cursor() as cur:
        owner = _owner(cur, profile_id)
        _, internal = _card(cur, owner, card_id, version)
        card = internal["card"]
        receipt = _receipt(owner, internal)
        own = next((edge for edge in internal["edges"] if edge["subject_id"] == str(owner["id"])), None)
        if own is None:
            _write(cur, owner, None, target_id=card["profile_id"], name=card["name"], label=card["label"],
                   notes=card["notes"], proof=_copied_proof(owner, internal, card["profile_id"]), receipts=[receipt], dismissed=True)
        for edge in internal["edges"]:
            raw = _raw_edge(cur, edge["id"])
            relationship_db.edit_in_transaction(cur, raw, label=raw["label"], notes=raw["notes"],
                proof=raw["analysis_evidence"], receipts=[receipt], dismissed=True)

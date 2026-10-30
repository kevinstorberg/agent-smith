from __future__ import annotations

from copy import deepcopy

from services.meetings import relationship_cards as cards

OWNER = {"id": "owner", "display_name": "Aaron Molloy", "revision": 1, "section_notes": {}, "section_evidence": {}}
JORDAN = {"id": "jordan", "display_name": "Jordan Doe", "nicknames": ["JD"], "aliases": []}
CASEY = {"id": "casey", "display_name": "Casey Quinn", "nicknames": [], "aliases": []}


def projected(text, edges=None, *, proof=None, owner=None, identities=None):
    row = {**(owner or OWNER), "section_notes": {"relationships": text},
           "section_evidence": {"relationships": proof or {"human": False, "status": "supported"}}}
    return cards.project(row, edges or [], identities or [OWNER, JORDAN, CASEY])


def edge(*, outgoing=True, notes="", human=False, generated=False, dismissed=False):
    return {"id": "out" if outgoing else "in", "subject_id": "owner" if outgoing else "jordan",
            "target_id": "jordan" if outgoing else "owner", "subject_name": "Aaron Molloy" if outgoing else "Jordan Doe",
            "target_name": "Jordan Doe" if outgoing else "Aaron Molloy", "label": "", "notes": notes,
            "revision": 1, "dismissed": dismissed, "history": [], "claim_count": 2,
            "analysis_evidence": {"human": human, **({"status": "supported", "generated_at": "2026-10-30"} if generated else {})}}


def test_legacy_arrow_sections_are_lossless_and_current_blank_edges_share_the_person_card():
    text = "Aaron → Jordan Doe: Values Jordan’s judgment.\n\nAaron -> Casey Quinn (colleague): Values Casey’s technical judgment."
    result = projected(text, [edge()])
    assert [(item["name"], item["notes"]) for item in result["relationship_cards"]] == [
        ("Casey Quinn", "Values Casey’s technical judgment."), ("Jordan Doe", "Values Jordan’s judgment.")]
    assert result["relationship_unassigned"] is None
    parsed = cards.parse_legacy(text, OWNER, [OWNER, JORDAN, CASEY])
    assert sum(part["end"] - part["start"] for part in parsed["parts"]) == len(text)


def test_outer_full_name_wins_and_inline_name_remains_unlinked_without_an_explicit_alias():
    owner = {"id": "ariella", "display_name": "Ariella Bak", "revision": 1}
    people = [owner, {"id": "aaron", "display_name": "Aaron Molloy"}, {"id": "kevin", "display_name": "Kevin Storberg"}]
    result = projected("Aaron Molloy (Aaron → Ariella): Trusts her operational judgment. Kevin: Values his technical perspective.", owner=owner, identities=people)
    assert [(item["name"], item["profile_id"], item["notes"]) for item in result["relationship_cards"]] == [
        ("Aaron Molloy", "aaron", "Trusts her operational judgment."), ("Kevin", None, "Values his technical perspective.")]


def test_short_target_can_only_use_one_existing_endpoint_and_never_discover_a_profile():
    people = [OWNER, JORDAN, CASEY]
    assert projected("Aaron → Jordan: Existing context.", identities=people)["relationship_cards"][0]["profile_id"] is None
    people = [OWNER, {**JORDAN, "endpoint": True}, CASEY]
    assert projected("Aaron → Jordan: Existing context.", identities=people)["relationship_cards"][0]["profile_id"] == "jordan"
    people.append({"id": "other-jordan", "display_name": "Jordan Smith", "endpoint": True})
    assert projected("Aaron → Jordan: Existing context.", identities=people)["relationship_cards"][0]["profile_id"] is None


def test_markdown_named_headers_and_unstructured_prefix_keep_all_input():
    text = "A preserved general observation.\n\n## JD\nTrusts careful judgment.\n\n**Casey Quinn:** Values clear execution."
    result = projected(text)
    assert [item["name"] for item in result["relationship_cards"]] == ["Casey Quinn", "Jordan Doe"]
    assert result["relationship_unassigned"]["notes"] == "A preserved general observation."
    assert projected("Overall: Jordan was mentioned in an ordinary sentence.")["relationship_cards"] == []


def test_reciprocal_order_never_changes_the_one_current_outgoing_analysis_or_version():
    own = edge(notes="Current assessment.", generated=True)
    incoming = edge(outgoing=False, notes="Other person’s assessment.", generated=True)
    first = projected("Aaron → Jordan Doe: Previous analysis.", [own, incoming])
    second = projected("Aaron → Jordan Doe: Previous analysis.", [incoming, own])
    assert first["relationship_cards"] == second["relationship_cards"]
    assert len(first["relationship_cards"]) == 1
    assert first["relationship_cards"][0]["notes"] == "Current assessment."


def test_human_ownership_and_explicit_clears_outrank_automatic_analysis():
    incoming = edge(outgoing=False, notes="", human=True)
    result = projected("Aaron → Jordan Doe: Earlier automatic analysis.", [edge(notes="Automatic assessment.", generated=True), incoming])
    assert result["relationship_cards"][0]["notes"] == ""
    assert result["relationship_cards"][0]["human"]
    result = projected("Aaron → Jordan Doe: My saved analysis.", [incoming], proof={"human": True})
    assert result["relationship_cards"][0]["notes"] == "My saved analysis."
    result = projected("", [edge(notes="Automatic assessment.", generated=True)], proof={"human": True})
    assert result["relationship_cards"][0]["notes"] == ""
    edited = edge(notes="Explicit new edit.", human=True)
    edited["history"] = [{"action": "legacy_import", "profile_id": "owner", "keys": [],
                           "legacy_state": cards.legacy_state({"section_notes": {"relationships": ""}, "section_evidence": {"relationships": {"human": True}}})}]
    result = projected("", [edited], proof={"human": True})
    assert result["relationship_cards"][0]["notes"] == "Explicit new edit."


def test_stale_attempted_output_does_not_resurrect_legacy_and_dismissal_removes_the_card():
    stale = {**edge(generated=True), "analysis_stale": True}
    result = projected("Aaron → Jordan Doe: Older available context.", [stale])
    assert result["relationship_cards"][0]["notes"] == ""
    assert result["relationship_cards"][0]["status"] == "stale"
    assert projected("Aaron → Jordan Doe: Older context.", [edge(dismissed=True)])["relationship_cards"] == []


def test_import_receipts_survive_nested_history_and_keep_older_named_text_suppressed():
    text = "Aaron → Jordan Doe: Older analysis."
    original = projected(text)
    key = original["_cards"]["profile:jordan"]["parts"][0]["key"]
    saved = edge(notes="My current analysis.", human=True)
    saved["history"] = [{"action": "merge", "before": [{"history": [{"action": "legacy_import", "profile_id": "owner", "keys": [key]}]}]}]
    result = projected(text, [saved])
    assert result["relationship_cards"][0]["notes"] == "My current analysis."
    assert result["_cards"]["profile:jordan"]["parts"] == []


def test_duplicate_exact_names_are_not_linked_and_do_not_claim_an_ambiguous_uuid():
    people = [OWNER, JORDAN, {**deepcopy(JORDAN), "id": "second-jordan"}]
    result = projected("Aaron → Jordan Doe: Unambiguous wording, ambiguous identity.", identities=people)
    assert result["relationship_cards"][0]["profile_id"] is None


def test_quoted_colons_code_and_nonperson_headings_do_not_create_a_person_card():
    text = 'Aaron → Jordan Doe: He quoted “A. Kevin: keep this inside the quote” and discussed the plan.\n\n## Overall\nA summary with Casey Quinn mentioned in ordinary prose.'
    result = projected(text, identities=[OWNER, JORDAN, CASEY, {"id": "kevin", "display_name": "Kevin Storberg"}])
    assert len(result["relationship_cards"]) == 1
    assert 'Kevin: keep this inside the quote' in result["relationship_cards"][0]["notes"]
    assert '## Overall' in result["relationship_cards"][0]["notes"]
    text = 'Aaron → "Jordan Doe": Keeps precise notes, including `A. Casey Quinn: code text`.'
    result = projected(text)
    assert len(result["relationship_cards"]) == 1 and result["relationship_cards"][0]["profile_id"] == "jordan"


def test_plural_possessives_do_not_swallow_the_next_named_relationship():
    for apostrophe in ("'", "’"):
        result = projected(f"Aaron → Jordan Doe: Respects James{apostrophe} judgment.\n\nAaron → Casey Quinn: Values Casey’s technical perspective.")
        assert [(card["name"], card["notes"]) for card in result["relationship_cards"]] == [
            ("Casey Quinn", "Values Casey’s technical perspective."), ("Jordan Doe", f"Respects James{apostrophe} judgment.")]
    result = projected("Aaron → Jordan Doe: He quoted 'A. Casey Quinn: quoted text' precisely.")
    assert len(result["relationship_cards"]) == 1

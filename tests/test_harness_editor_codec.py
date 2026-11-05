from __future__ import annotations

import pytest
import yaml
import json
from pathlib import Path

from services.harness.editor import compose, decode, descriptors


def skill(body=None):
    return {
        "body": body
        or "---\nname: sample\ndescription: Original description\ncustom:\n  nested: [one, false, 0, null]\n---\n\nComplete instructions.\n",
        "metadata": {
            "files": {"references/info.md": "Complete reference."},
            "custom_metadata": {"empty": ""},
        },
        "custom_content": ["keep", 0],
    }


def edited(original, **changes):
    draft = decode("skill", "sample", original)
    fields = {**draft["fields"], **changes}
    return compose(
        "skill",
        "sample",
        fields=fields,
        extensions=draft["extensions"],
        original_content=original,
        dirty_paths=["/fields/" + key for key in changes],
    )


def test_skill_descriptor_has_labeled_fields_examples_and_server_owned_choices():
    fields = descriptors()["types"]["skill"]["fields"]
    assert {field["key"] for field in fields} >= {
        "description",
        "instructions",
        "files",
    }
    assert all(field["label"] and field["placeholder"] for field in fields)


def test_skill_decode_preserves_unknown_nested_values_and_original_content():
    original = skill()
    draft = decode("skill", "sample", original)
    assert draft["capabilities"] == {"guided_supported": True, "unsupported_paths": []}
    assert draft["fields"]["description"] == "Original description"
    assert draft["fields"]["instructions"] == "\nComplete instructions.\n"
    assert draft["fields"]["files"] == [
        {"path": "references/info.md", "content": "Complete reference."}
    ]
    assert draft["extensions"]["frontmatter"] == {
        "custom": {"nested": ["one", False, 0, None]}
    }
    assert draft["original_content"] == original


def test_legacy_description_is_one_guided_field_with_a_preserved_compatibility_alias():
    original = skill()
    original["metadata"]["description"] = "Legacy alias"
    draft = decode("skill", "sample", original)
    assert draft["fields"]["description"] == "Original description"
    assert "description" not in draft["extensions"]["metadata"]
    assert (
        compose(
            "skill",
            "sample",
            fields=draft["fields"],
            extensions=draft["extensions"],
            original_content=original,
            dirty_paths=[],
        )
        == original
    )
    changed = edited(original, description="Updated description")
    assert changed["metadata"]["description"] == "Updated description"


def test_untouched_skill_preserves_exact_bytes_comments_and_version_inputs():
    original = skill(
        "---\r\n# Keep this comment\r\nname: sample\r\ndescription: 'Quoted'\r\n---\r\n\r\nFull instructions.\r\n"
    )
    draft = decode("skill", "sample", original)
    result = compose(
        "skill",
        "sample",
        fields=draft["fields"],
        extensions=draft["extensions"],
        original_content=original,
        dirty_paths=[],
    )
    assert result == original
    assert result is not original


def test_supporting_file_only_edit_preserves_untouched_document_bytes():
    original = skill(
        "---\r\n# Preserve comment\r\nname: sample\r\ndescription: 'Original description'\r\n---\r\n\r\nComplete instructions.\r\n"
    )
    result = edited(
        original, files=[{"path": "references/new.md", "content": "New reference."}]
    )
    assert result["body"] == original["body"]
    assert result["metadata"]["files"] == {"references/new.md": "New reference."}


def test_spurious_dirty_marker_does_not_rewrite_an_unchanged_value():
    original = skill(
        "---\n# Keep comment\nname: sample\ndescription: Original description\n---\nInstructions.\n"
    )
    assert edited(original, description="Original description") == original


def test_changed_skill_assembles_one_safe_header_and_complete_native_artifacts(
    tmp_path,
):
    from scripts.shared.fs import _sync_skills_to_target

    instructions = "Full context.\n" * 10_000 + "UNTRUNCATED FINAL SENTINEL"
    result = edited(
        skill(),
        description='When asked about "context": use this skill.',
        instructions=instructions,
    )
    header, body = result["body"].split("---\n", 2)[1:]
    parsed = yaml.safe_load(header)
    assert parsed["name"] == "sample"
    assert parsed["description"] == 'When asked about "context": use this skill.'
    assert parsed["custom"] == {"nested": ["one", False, 0, None]}
    assert body == instructions
    assert result["custom_content"] == ["keep", 0]
    assert result["metadata"]["custom_metadata"] == {"empty": ""}
    _sync_skills_to_target(
        {"sample": {"skill_md": result["body"], "files": result["metadata"]["files"]}},
        tmp_path,
        False,
    )
    assert (tmp_path / "sample/SKILL.md").read_text() == result["body"]
    assert (tmp_path / "sample/references/info.md").read_text() == "Complete reference."


@pytest.mark.parametrize(
    "fragment",
    [
        "custom: !custom value",
        "custom: &loop [*loop]",
        "custom: 2026-11-05",
        "custom: .inf",
        "? [a, b]\n: value",
    ],
)
def test_unsupported_yaml_remains_explicitly_preserved_without_guided_rewrite(fragment):
    original = skill(
        f"---\nname: sample\ndescription: Trigger\n{fragment}\n---\nInstructions.\n"
    )
    draft = decode("skill", "sample", original)
    assert draft["capabilities"]["guided_supported"] is False
    assert draft["capabilities"]["unsupported_paths"]
    assert draft["original_content"] == original
    assert (
        compose(
            "skill",
            "sample",
            fields=draft["fields"],
            extensions=draft["extensions"],
            original_content=original,
            dirty_paths=[],
        )
        == original
    )
    with pytest.raises(ValueError, match="guided|unsupported"):
        compose(
            "skill",
            "sample",
            fields={"description": "Changed"},
            extensions={},
            original_content=original,
            dirty_paths=["/fields/description"],
        )


@pytest.mark.parametrize(
    "files",
    [
        [{"path": "../escape", "content": "x"}],
        [{"path": "SKILL.md", "content": "overwrite"}],
        [{"path": "a//b", "content": "one"}, {"path": "a/b", "content": "two"}],
    ],
)
def test_skill_supporting_file_errors_name_the_field_without_exposing_content(files):
    with pytest.raises(ValueError, match="fields.files") as error:
        edited(skill(), files=files)
    assert "overwrite" not in str(error.value)


@pytest.mark.parametrize(
    "paths",
    [
        ["References/info.md", "references/info.md"],
        ["references", "references/info.md"],
    ],
)
def test_supporting_files_cannot_alias_or_become_each_others_parent(paths):
    with pytest.raises(ValueError, match="fields.files"):
        edited(
            skill(),
            files=[
                {"path": path, "content": "Retain each distinct file."}
                for path in paths
            ],
        )


def test_shared_container_aliases_have_bounded_explicit_raw_fallback():
    aliases = "base: &base [one, two]\n"
    for index in range(8):
        previous = "base" if index == 0 else f"level{index - 1}"
        aliases += f"level{index}: &level{index} [*{previous}, *{previous}]\n"
    original = skill(
        f"---\nname: sample\ndescription: Trigger\n{aliases}---\nComplete instructions."
    )
    decoded = decode("skill", "sample", original)
    assert decoded["capabilities"]["guided_supported"] is False
    assert decoded["extensions"] == {}
    assert decoded["raw"] == original["body"]
    assert (
        compose(
            "skill",
            "sample",
            fields={},
            extensions={},
            original_content=original,
            dirty_paths=[],
        )
        == original
    )


def test_scalar_yaml_aliases_remain_supported_without_container_expansion():
    original = skill(
        "---\nname: sample\ndescription: &trigger Review changes\ncustom: *trigger\n---\nComplete instructions."
    )
    decoded = decode("skill", "sample", original)
    assert decoded["capabilities"]["guided_supported"] is True
    assert decoded["extensions"]["frontmatter"]["custom"] == "Review changes"


def test_dirty_path_updates_one_unknown_leaf_preserving_neighbor_and_empty_values():
    original = skill()
    draft = decode("skill", "sample", original)
    draft["extensions"]["frontmatter"]["custom"]["nested"][0] = "updated"
    result = compose(
        "skill",
        "sample",
        fields=draft["fields"],
        extensions=draft["extensions"],
        original_content=original,
        dirty_paths=["/extensions/frontmatter/custom/nested/0"],
    )
    header = yaml.safe_load(result["body"].split("---\n", 2)[1])
    assert header["custom"]["nested"] == ["updated", False, 0, None]


def test_skill_rename_reassembles_name_header_without_duplicating_it():
    original = skill()
    draft = decode("skill", "sample", original)
    result = compose(
        "skill",
        "renamed",
        source_name="sample",
        fields=draft["fields"],
        extensions=draft["extensions"],
        original_content=original,
        dirty_paths=[],
    )
    assert yaml.safe_load(result["body"].split("---\n", 2)[1])["name"] == "renamed"
    assert result["body"].count("---\n") == 2


def test_duplicate_yaml_keys_cannot_be_silently_discarded():
    original = skill(
        "---\nname: sample\ndescription: First\ndescription: Second\n---\nInstructions."
    )
    draft = decode("skill", "sample", original)
    assert not draft["capabilities"]["guided_supported"]
    assert draft["original_content"] == original


def test_offline_skill_browser_fixture_is_actual_backend_composition():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/harness_editor_skill.json").read_text()
    )
    assert fixture["descriptors"]["common"] == descriptors()["common"]
    assert fixture["descriptors"]["types"]["skill"] == descriptors()["types"]["skill"]
    for key in ("created", "existing", "updated"):
        item = fixture[key]
        draft = fixture[key + "_draft"]
        assert decode("skill", item["name"], item["content"]) == draft
        rendered = compose(
            "skill",
            item["name"],
            fields=draft["fields"],
            extensions=draft["extensions"],
        )
        assert rendered == item["content"]

from __future__ import annotations

from copy import deepcopy
import json

from scripts.shared.path_safety import relative_parts
from services.harness.frontmatter import (
    UnsupportedDocument,
    compose_agent_file,
    compose_document,
    reject_duplicate_header,
    split_document,
    validate_raw_skill,
)
from services.harness.editor_values import mapping as _mapping, text as _text
from services.harness.editor_codecs import (
    compose_other,
    decode_other,
    render_rule_clone as render_rule_clone,
    validate_hook,
    validate_tool,
)


def _field(key, label, kind, placeholder, *, required=False, **settings):
    return {
        "key": key,
        "label": label,
        "kind": kind,
        "placeholder": placeholder,
        "required": required,
        **settings,
    }


def descriptors() -> dict:
    from scripts.shared.agents import AGENT_TARGETS, VIRTUAL_AGENTS
    from scripts.shared.validation import MAX_NAME_LENGTH

    result = {
        "common": [
            _field(
                "name",
                "Name",
                "text",
                "review_changes",
                required=True,
                max_length=MAX_NAME_LENGTH,
                default="",
            ),
            _field(
                "project",
                "Project",
                "text",
                "agent-smith (leave empty to share)",
                default="",
            ),
            _field("sort_key", "Sort order", "number", "5", default=0, minimum=0),
            _field(
                "agents",
                "Available to agents",
                "multiselect",
                "Choose the agents that can use this item",
                choices=[*AGENT_TARGETS, *VIRTUAL_AGENTS],
                default=list(AGENT_TARGETS),
            ),
            _field(
                "subagents",
                "Subagent audience",
                "strings",
                "reviewer (or * for every subagent)",
                default=[],
            ),
            _field("enabled", "Enabled", "boolean", "Enable this item", default=True),
            _field(
                "device",
                "Initial device",
                "text",
                "* or my-macbook",
                default="*",
                create_only=True,
            ),
            _field(
                "repo",
                "Initial repository",
                "text",
                "* or /Users/me/projects/agent-smith",
                default="*",
                create_only=True,
            ),
        ],
        "types": {
            "skill": {
                "label": "Skill",
                "initial_extensions": {"frontmatter": {}, "metadata": {}},
                "fields": [
                    _field(
                        "description",
                        "Description / when to use",
                        "text",
                        "Use when reviewing changes for security and correctness.",
                        required=True,
                        default="",
                    ),
                    _field(
                        "instructions",
                        "Instructions",
                        "markdown",
                        "Read the changed files, explain the findings, and cite concrete evidence.",
                        required=True,
                        default="",
                    ),
                    _field(
                        "files",
                        "Supporting files",
                        "rows",
                        "references/review-checklist.md",
                        default=[],
                        fields=[
                            _field(
                                "path",
                                "File path",
                                "text",
                                "references/review-checklist.md",
                                required=True,
                            ),
                            _field(
                                "content",
                                "File content",
                                "markdown",
                                "# Review checklist\n\nCheck inputs, errors, and boundary conditions.",
                            ),
                        ],
                    ),
                ],
            }
        },
    }
    from services.harness.editor_descriptors import additional_types

    result["types"].update(additional_types(_field))
    return result


def _decode_skill(content):
    header, instructions = split_document(content["body"])
    metadata = _mapping(content.get("metadata", {}), "content.metadata")
    description = header.get("description", metadata.get("description", ""))
    _text(description, "fields.description")
    files = _mapping(metadata.get("files", {}), "content.metadata.files")
    for value in files.values():
        _text(value, "fields.files.content")
    return (
        {
            "description": description,
            "instructions": instructions,
            "files": [
                {"path": path, "content": value} for path, value in files.items()
            ],
        },
        {
            "frontmatter": {
                key: value
                for key, value in header.items()
                if key not in {"name", "description"}
            },
            "metadata": {
                key: value
                for key, value in metadata.items()
                if key not in {"files", "description"}
            },
        },
    )


def decode(kind: str, name: str, content: dict) -> dict:
    if kind not in descriptors()["types"]:
        raise ValueError("item_type is unsupported")
    original = deepcopy(content)
    unsupported = []
    diagnostics = []
    try:
        _mapping(content, "content")
        fields, extensions = (
            _decode_skill(content) if kind == "skill" else decode_other(kind, content)
        )
    except (UnsupportedDocument, ValueError, KeyError) as error:
        fields, extensions = {}, {}
        location = str(error).split(" ", 1)[0]
        unsupported = [
            "/" + location.replace(".", "/")
            if location.startswith(("content", "fields"))
            else "/content"
        ]
        diagnostics = [{"path": unsupported[0], "message": str(error)}]
    return {
        "fields": fields,
        "extensions": extensions,
        "original_content": original,
        "raw": raw_definition(kind, name, content),
        "capabilities": {
            "guided_supported": not unsupported,
            "unsupported_paths": unsupported,
        },
        **({"diagnostics": diagnostics} if diagnostics else {}),
    }


def _pointer(path):
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("dirty_paths must contain field paths")
    parts = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
    if parts[0] not in {"fields", "extensions"}:
        raise ValueError("dirty_paths must identify fields or extensions")
    return parts


def _child(value, key):
    try:
        return value[int(key)] if isinstance(value, list) else value[key]
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError("dirty_paths must identify existing draft fields") from None


def _apply_dirty(original, draft, paths):
    merged = deepcopy(original)
    for path in paths:
        parts = _pointer(path)
        target, desired = merged, draft
        for part in parts[:-1]:
            target, desired = _child(target, part), _child(desired, part)
        key = parts[-1]
        if (
            isinstance(target, dict)
            and isinstance(desired, dict)
            and key not in desired
        ):
            target.pop(key, None)
        else:
            value = deepcopy(_child(desired, key))
            if isinstance(target, list):
                try:
                    target[int(key)] = value
                except (IndexError, ValueError):
                    raise ValueError(
                        "dirty_paths must identify existing draft fields"
                    ) from None
            elif isinstance(target, dict):
                target[key] = value
            else:
                raise ValueError("dirty_paths must identify editable draft fields")
    return merged


def _skill_files(rows):
    if not isinstance(rows, list):
        raise ValueError("fields.files must be a list of file rows")
    files = {}
    normalized = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"fields.files.{index} must contain file rows")
        path = row.get("path")
        try:
            parts = relative_parts(path)
        except ValueError:
            raise ValueError(
                f"fields.files.{index}.path must identify a safe relative child path"
            ) from None
        components = tuple(part.casefold() for part in parts)
        if components[0] == "skill.md" or any(
            components[: len(previous)] == previous
            or previous[: len(components)] == components
            for previous in normalized
        ):
            raise ValueError(
                f"fields.files.{index}.path must be unique and must not replace SKILL.md"
            )
        normalized.add(components)
        files[path] = _text(row.get("content"), f"fields.files.{index}.content")
    return files


def compose(
    kind: str,
    name: str,
    *,
    fields: dict,
    extensions: dict,
    original_content: dict | None = None,
    dirty_paths: list[str] | None = None,
    source_name: str | None = None,
    validate: bool = True,
    clone_as_skill: bool = False,
    agents: list[str] | None = None,
) -> dict:
    original = (
        original_content
        if original_content is not None
        else {"body": "", "metadata": {}}
    )
    baseline = decode(kind, source_name or name, original)
    paths = (
        ["/fields", "/extensions"] if original_content is None else (dirty_paths or [])
    )
    if not paths and (source_name is None or source_name == name):
        return deepcopy(original)
    if not baseline["capabilities"]["guided_supported"]:
        raise ValueError(
            "guided editing is unsupported for the preserved document; use Raw"
        )
    merged = _apply_dirty(
        {"fields": baseline["fields"], "extensions": baseline["extensions"]},
        {"fields": fields, "extensions": extensions},
        paths,
    )
    if (
        original_content is not None
        and merged
        == {"fields": baseline["fields"], "extensions": baseline["extensions"]}
        and (source_name is None or source_name == name)
    ):
        return deepcopy(original)
    values = merged["fields"]
    extras = merged["extensions"]
    if kind != "skill":
        return compose_other(
            kind,
            name,
            values,
            extras,
            original,
            paths,
            validate=validate,
            clone_as_skill=clone_as_skill,
            agents=agents,
        )
    body_changed = (
        original_content is None
        or (source_name is not None and source_name != name)
        or any(
            path == "/fields"
            or path == "/extensions"
            or path.startswith(
                (
                    "/fields/description",
                    "/fields/instructions",
                    "/extensions/frontmatter",
                )
            )
            for path in paths
        )
    )
    description = _text(
        values.get("description"),
        "fields.description",
        required=validate and body_changed,
    )
    instructions = _text(
        values.get("instructions"),
        "fields.instructions",
        required=validate and body_changed,
    )
    reject_duplicate_header(instructions)
    frontmatter = deepcopy(
        _mapping(extras.get("frontmatter", {}), "extensions.frontmatter")
    )
    if {"name", "description"} & frontmatter.keys():
        raise ValueError(
            "extensions.frontmatter must not replace managed name or description fields"
        )
    result = deepcopy(original)
    if body_changed:
        result["body"] = compose_document(
            {"name": name, "description": description, **frontmatter}, instructions
        )
    metadata = _mapping(extras.get("metadata", {}), "extensions.metadata")
    if {"files", "description"} & metadata.keys():
        raise ValueError(
            "extensions.metadata must not replace managed file or description fields"
        )
    result["metadata"] = {**metadata, "files": _skill_files(values.get("files", []))}
    if "description" in original.get("metadata", {}):
        result["metadata"]["description"] = (
            description
            if any(
                path == "/fields" or path.startswith("/fields/description")
                for path in paths
            )
            else original["metadata"]["description"]
        )
    return result


def raw_definition(kind, name, content):
    if kind in {"tool", "hook"}:
        return (
            json.dumps(content.get("metadata", {}), ensure_ascii=False, indent=2) + "\n"
        )
    if kind == "agent":
        return compose_agent_file(content.get("body", ""), content.get("metadata", {}))
    return content.get("body", "")


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("raw contains duplicate JSON keys")
        result[key] = value
    return result


def compose_raw(
    kind: str,
    name: str,
    raw: str | None,
    original_content: dict | None = None,
    *,
    allow_unchanged=True,
    clone_as_skill=False,
    agents=None,
) -> dict:
    text = _text(raw, "raw")
    original = (
        original_content
        if original_content is not None
        else {"body": "", "metadata": {}}
    )
    if allow_unchanged and text == raw_definition(kind, name, original):
        return deepcopy(original)
    if kind in {"tool", "hook"}:
        try:
            metadata = json.loads(text, object_pairs_hook=_unique_json)
        except (ValueError, TypeError):
            raise ValueError(
                "raw must contain a JSON object without duplicate keys"
            ) from None
        _mapping(metadata, "raw")
        if kind == "tool":
            validate_tool(metadata)
        else:
            validate_hook(metadata, agents)
        return {**deepcopy(original), "metadata": metadata}
    if kind == "skill":
        validate_raw_skill(text, name)
        return {**deepcopy(original), "body": text}
    if kind == "agent":
        metadata, instructions = split_document(text)
        if _text(metadata.get("name", ""), "raw.name", required=True) != name:
            raise ValueError("raw.name must match the Name field")
        _text(metadata.get("description", ""), "raw.description", required=True)
        _text(instructions, "raw.instructions", required=True)
        return {**deepcopy(original), "body": instructions, "metadata": metadata}
    if kind == "rule":
        _text(text, "raw.instructions", required=True)
        result = {**deepcopy(original), "body": text}
        if clone_as_skill:
            render_rule_clone({"name": name, "content": result})
        return result
    raise ValueError("item_type is unsupported")

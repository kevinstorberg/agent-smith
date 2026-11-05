from __future__ import annotations

import math
from copy import deepcopy

import yaml


class UnsupportedDocument(ValueError):
    pass


class _UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        if not isinstance(node, yaml.MappingNode):
            raise UnsupportedDocument("content.body.frontmatter must be a mapping")
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise UnsupportedDocument(
                    "content.body.frontmatter contains duplicate or unsupported keys"
                )
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def json_value(value, ancestors: frozenset[int] = frozenset()) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if not isinstance(value, (list, dict)) or id(value) in ancestors:
        return False
    ancestry = ancestors | {id(value)}
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and json_value(child, ancestry)
            for key, child in value.items()
        )
    return all(json_value(child, ancestry) for child in value)


def _shared_containers(value, visited=None):
    if not isinstance(value, (list, dict)):
        return False
    if visited is None:
        visited = set()
    identity = id(value)
    if identity in visited:
        return True
    visited.add(identity)
    children = value.values() if isinstance(value, dict) else value
    return any(_shared_containers(child, visited) for child in children)


def _segments(text: str) -> tuple[str | None, str]:
    if not isinstance(text, str):
        raise UnsupportedDocument("content.body must be text")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None, text
    closing = next(
        (
            index
            for index in range(1, len(lines))
            if lines[index].rstrip("\r\n") == "---"
        ),
        None,
    )
    if closing is None:
        raise UnsupportedDocument(
            "content.body.frontmatter is missing its closing delimiter"
        )
    return "".join(lines[1:closing]), "".join(lines[closing + 1 :])


def split_document(text: str) -> tuple[dict, str]:
    header, instructions = _segments(text)
    if header is None:
        return {}, instructions
    try:
        metadata = yaml.load(header, Loader=_UniqueLoader)
    except (yaml.YAMLError, ValueError, TypeError, RecursionError):
        raise UnsupportedDocument(
            "content.body.frontmatter contains unsupported or invalid YAML"
        ) from None
    if metadata is None:
        metadata = {}
    if _shared_containers(metadata):
        raise UnsupportedDocument(
            "content.body.frontmatter contains shared container aliases; preserve this document in Raw"
        )
    if not isinstance(metadata, dict) or not json_value(metadata):
        raise UnsupportedDocument(
            "content.body.frontmatter must contain only JSON-compatible mapping values"
        )
    return metadata, instructions


def validate_raw_skill(text: str, name: str) -> None:
    header, instructions = _segments(text)
    try:
        node = (
            yaml.compose(header, Loader=yaml.SafeLoader) if header is not None else None
        )
    except yaml.YAMLError:
        raise ValueError("raw.frontmatter contains invalid YAML") from None
    if not isinstance(node, yaml.MappingNode):
        raise ValueError("raw.frontmatter must contain a name and description mapping")
    values = {}
    for key, value in node.value:
        if (
            not isinstance(key, yaml.ScalarNode)
            or key.tag != "tag:yaml.org,2002:str"
            or key.value in values
        ):
            raise ValueError("raw.frontmatter contains duplicate or unsupported keys")
        values[key.value] = value
    for key in ("name", "description"):
        value = values.get(key)
        if (
            not isinstance(value, yaml.ScalarNode)
            or value.tag != "tag:yaml.org,2002:str"
            or not value.value.strip()
        ):
            raise ValueError(f"raw.frontmatter.{key} must be nonblank text")
    if values["name"].value != name:
        raise ValueError("raw.frontmatter.name must match common.name")
    if not instructions.strip():
        raise ValueError("raw.instructions must be nonblank text")
    reject_duplicate_header(instructions)


def reject_duplicate_header(instructions: str) -> None:
    try:
        header, _ = split_document(instructions.lstrip("\r\n"))
    except UnsupportedDocument:
        return
    if "name" in header or "description" in header:
        raise ValueError(
            "fields.instructions must not contain another skill frontmatter header"
        )


def compose_document(
    metadata: dict,
    instructions: str,
    *,
    sort_keys=False,
    allow_unicode=True,
    width=1_000_000,
) -> str:
    if not isinstance(metadata, dict) or not json_value(metadata):
        raise ValueError("frontmatter must contain only JSON-compatible mapping values")
    if not isinstance(instructions, str):
        raise ValueError("instructions must be text")
    if not metadata:
        return instructions
    header = yaml.safe_dump(
        deepcopy(metadata),
        allow_unicode=allow_unicode,
        sort_keys=sort_keys,
        width=width,
    )
    return f"---\n{header}---\n{instructions}"


def compose_agent_file(
    body: str, metadata: dict, scoped_rules: list | None = None
) -> str:
    parts = (
        [compose_document(metadata, "", sort_keys=True, allow_unicode=False, width=80)]
        if metadata
        else []
    )
    parts.append(body.rstrip())
    if scoped_rules:
        parts.append("\n\n# Rules\n")
        parts.extend(rule["content"]["body"].rstrip() for rule in scoped_rules)
    return "\n\n".join(parts) + "\n"

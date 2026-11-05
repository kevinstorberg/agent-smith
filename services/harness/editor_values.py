from __future__ import annotations

import re
from copy import deepcopy

from services.harness.frontmatter import json_value


def mapping(value, path):
    if not isinstance(value, dict) or not json_value(value):
        raise ValueError(f"{path} must be a JSON-compatible object")
    return value


def text(value, path, *, required=False, single_line=False):
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{path} must be {'nonblank ' if required else ''}text")
    if "\0" in value or (
        single_line and any(character in value for character in "\r\n")
    ):
        raise ValueError(f"{path} contains unsupported control characters")
    return value


def strings(value, path):
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a list of text values")
    return [
        text(item, f"{path}.{index}", single_line=True)
        for index, item in enumerate(value)
    ]


def pair_rows(value, path):
    return [
        {"key": key, "value": text(child, path + ".value")}
        for key, child in mapping(value, path).items()
    ]


def string_pairs(rows, path, *, headers=False):
    if not isinstance(rows, list):
        raise ValueError(f"{path} must be key/value rows")
    values, seen = {}, set()
    for index, row in enumerate(rows):
        row = mapping(row, f"{path}.{index}")
        key = text(
            row.get("key"), f"{path}.{index}.key", required=True, single_line=True
        )
        pattern = (
            r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+" if headers else r"[A-Za-z_][A-Za-z0-9_]*"
        )
        if not re.fullmatch(pattern, key):
            raise ValueError(
                f"{path}.{index}.key is not a valid {'HTTP header' if headers else 'environment variable'} name"
            )
        identity = key.casefold() if headers else key
        if identity in seen:
            raise ValueError(f"{path}.{index}.key must be unique")
        seen.add(identity)
        values[key] = text(
            row.get("value"), f"{path}.{index}.value", single_line=headers
        )
    return values


def changed(paths, field):
    prefix = "/fields/" + field
    return any(
        path == "/fields" or path == prefix or path.startswith(prefix + "/")
        for path in paths
    )


def metadata_with_extensions(original, extensions, managed):
    extras = mapping(extensions.get("metadata", {}), "extensions.metadata")
    if set(extras) & set(managed):
        raise ValueError("extensions.metadata must not replace managed fields")
    return {
        **deepcopy(extras),
        **{key: deepcopy(value) for key, value in original.items() if key in managed},
    }


def optional_text(metadata, key, value, path):
    value = text(value, path, single_line=True)
    if value:
        metadata[key] = value
    else:
        metadata.pop(key, None)

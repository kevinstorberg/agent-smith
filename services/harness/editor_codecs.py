from __future__ import annotations

from copy import deepcopy
import math
import re
from urllib.parse import urlsplit

from services.harness.editor_values import (
    changed,
    mapping,
    metadata_with_extensions,
    optional_text,
    pair_rows,
    string_pairs,
    strings,
    text,
)
from services.harness.frontmatter import (
    UnsupportedDocument,
    compose_document,
    split_document,
)

HOOK_FIELDS = {"type", "command", "prompt", "model", "timeout", "async"}
AGENT_FIELDS = {
    "description": "description",
    "model": "model",
    "tools": "tools",
    "disallowed_tools": "disallowedTools",
    "skills": "skills",
}


def _legacy_list(value, path):
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return strings(value, path)


def decode_other(kind, content):
    metadata = mapping(content.get("metadata", {}), "content.metadata")
    body = text(content.get("body"), "content.body")
    if kind == "rule":
        description = metadata.get("skill_description", "")
        if not description:
            try:
                header, _ = split_document(body)
                description = header.get("description", "")
            except UnsupportedDocument:
                pass
        return {
            "instructions": body,
            "clone_description": text(description, "fields.clone_description"),
        }, {
            "metadata": {
                key: value
                for key, value in metadata.items()
                if key != "skill_description"
            }
        }
    if kind == "tool":
        if "command" in metadata and "url" in metadata:
            raise ValueError("content.metadata must select one transport")
        oauth = mapping(metadata.get("oauth", {}), "content.metadata.oauth")
        fields = {
            "transport": "stdio" if "command" in metadata else "http",
            "notes": body,
            "description": text(metadata.get("description", ""), "fields.description"),
            "command": text(metadata.get("command", ""), "fields.command"),
            "url": text(metadata.get("url", ""), "fields.url"),
            "args": strings(metadata.get("args", []), "fields.args"),
            "env": pair_rows(metadata.get("env", {}), "fields.env"),
            "headers": pair_rows(metadata.get("headers", {}), "fields.headers"),
            "oauth_client_id": text(
                oauth.get("clientId", ""), "fields.oauth_client_id"
            ),
        }
        return fields, {
            "metadata": {
                key: value
                for key, value in metadata.items()
                if key
                not in {
                    "description",
                    "command",
                    "url",
                    "args",
                    "env",
                    "headers",
                    "oauth",
                }
            },
            "oauth": {key: value for key, value in oauth.items() if key != "clientId"},
        }
    if kind == "hook":
        from services.api.models.hook import HOOK_EVENT_MAP

        event = text(metadata.get("event", "pre_tool_use"), "fields.event")
        if not any(event in choices for choices in HOOK_EVENT_MAP.values()):
            raise ValueError("fields.event is not a supported canonical event")
        handlers = metadata.get("hooks", [])
        if not isinstance(handlers, list):
            raise ValueError("fields.handlers must be a list")
        rows = []
        for index, handler in enumerate(handlers):
            handler = mapping(handler, f"fields.handlers.{index}")
            if handler.get("type") not in {"command", "prompt", "agent"}:
                raise ValueError(
                    f"fields.handlers.{index}.type is unsupported for guided editing"
                )
            rows.append(
                {
                    **{
                        key: value
                        for key, value in handler.items()
                        if key in HOOK_FIELDS
                    },
                    "settings": {
                        key: value
                        for key, value in handler.items()
                        if key not in HOOK_FIELDS
                    },
                }
            )
        permissions = mapping(metadata.get("permissions", {}), "fields.permissions")
        if set(permissions) - {"allow"}:
            raise ValueError("fields.permissions contains unsupported permission modes")
        return {
            "event": event,
            "matcher": text(metadata.get("matcher", ""), "fields.matcher"),
            "notes": body,
            "default_model": text(metadata.get("model", ""), "fields.default_model"),
            "handlers": rows,
            "permissions": strings(permissions.get("allow", []), "fields.permissions"),
        }, {
            "metadata": {
                key: value
                for key, value in metadata.items()
                if key not in {"event", "matcher", "model", "hooks", "permissions"}
            }
        }
    if kind == "agent":
        fields = {"instructions": body, "inherit_tools": "tools" not in metadata}
        for field, key in AGENT_FIELDS.items():
            fields[field] = (
                _legacy_list(metadata.get(key, []), "fields." + field)
                if field in {"tools", "disallowed_tools", "skills"}
                else text(metadata.get(key, ""), "fields." + field)
            )
        return fields, {
            "metadata": {
                key: value
                for key, value in metadata.items()
                if key not in {*AGENT_FIELDS.values(), "name"}
            }
        }
    raise ValueError("item_type is unsupported")


def validate_tool(metadata):
    from scripts.shared.agents import AGENT_TARGETS

    if ("command" in metadata) == ("url" in metadata):
        raise ValueError(
            "fields.transport must select exactly one local command or HTTP server"
        )
    if "command" in metadata:
        text(metadata["command"], "fields.command", required=True, single_line=True)
        strings(metadata.get("args", []), "fields.args")
        string_pairs(pair_rows(metadata.get("env", {}), "fields.env"), "fields.env")
    else:
        url = text(metadata["url"], "fields.url", required=True, single_line=True)
        if not re.match(r"^\$\{\w+\}(?:[/#?]|$)", url):
            try:
                parts = urlsplit(re.sub(r"\$\{\w+\}", "1", url))
                if parts.scheme not in {"http", "https"} or not parts.hostname:
                    raise ValueError()
                _ = parts.port
            except ValueError:
                raise ValueError(
                    "fields.url must be an absolute HTTP(S) URL or an environment template"
                ) from None
        string_pairs(
            pair_rows(metadata.get("headers", {}), "fields.headers"),
            "fields.headers",
            headers=True,
        )
    for target in AGENT_TARGETS.values():
        target["mcp_transform"](metadata)


def _handlers(rows):
    if not isinstance(rows, list):
        raise ValueError("fields.handlers must be a list of handler rows")
    handlers = []
    for index, row in enumerate(rows):
        path = f"fields.handlers.{index}"
        row = mapping(row, path)
        extras = mapping(row.get("settings", {}), path + ".settings")
        if set(extras) & HOOK_FIELDS:
            raise ValueError(path + ".settings must not replace managed handler fields")
        handler = {
            **deepcopy(extras),
            **{key: value for key, value in row.items() if key in HOOK_FIELDS},
        }
        kind = handler.get("type")
        if kind not in {"command", "prompt", "agent"}:
            raise ValueError(path + ".type must select command, prompt, or agent")
        text(
            handler.get("command" if kind == "command" else "prompt"),
            path + (".command" if kind == "command" else ".prompt"),
            required=True,
        )
        if kind == "command":
            if handler.get("model"):
                raise ValueError(
                    path + ".model is supported only for prompt or agent handlers"
                )
            handler.pop("model", None)
            handler.pop("prompt", None)
        else:
            handler.pop("command", None)
            handler.pop("async", None)
            if not handler.get("model"):
                handler.pop("model", None)
        if handler.get("timeout") is None:
            handler.pop("timeout", None)
        elif (
            isinstance(handler["timeout"], bool)
            or not isinstance(handler["timeout"], (int, float))
            or not math.isfinite(handler["timeout"])
            or handler["timeout"] <= 0
        ):
            raise ValueError(path + ".timeout must be a finite positive number")
        if "async" in handler and not isinstance(handler["async"], bool):
            raise ValueError(path + ".async must be true or false")
        handlers.append(handler)
    return handlers


def validate_hook(metadata, agents=None):
    from services.api.models.hook import HOOK_EVENT_MAP, compile_hook_settings

    if not any(metadata.get("event") in events for events in HOOK_EVENT_MAP.values()):
        raise ValueError("fields.event must select a supported canonical event")
    fields, _ = decode_other("hook", {"body": "", "metadata": metadata})
    _handlers(fields["handlers"])
    for agent in agents or ["claude"]:
        if agent in HOOK_EVENT_MAP:
            try:
                compile_hook_settings(
                    [{"name": "editor", "content": {"metadata": metadata}}], agent
                )
            except ValueError as error:
                message = str(error).replace("Hook editor: metadata.", "fields.")
                message = message.replace("fields.hooks", "fields.handlers")
                message = message.replace("fields.model", "fields.default_model")
                message = message.replace(
                    "fields.permissions.allow", "fields.permissions"
                )
                raise ValueError(message) from None


def compose_other(
    kind,
    name,
    fields,
    extensions,
    original,
    paths,
    *,
    validate=True,
    clone_as_skill=False,
    agents=None,
):
    metadata = mapping(original.get("metadata", {}), "content.metadata")
    result = deepcopy(original)
    if kind == "rule":
        metadata = metadata_with_extensions(metadata, extensions, {"skill_description"})
        if changed(paths, "instructions"):
            result["body"] = text(
                fields.get("instructions"), "fields.instructions", required=validate
            )
        if changed(paths, "clone_description"):
            optional_text(
                metadata,
                "skill_description",
                fields.get("clone_description", ""),
                "fields.clone_description",
            )
        result["metadata"] = metadata
        if clone_as_skill and validate:
            text(
                fields.get("clone_description"),
                "fields.clone_description",
                required=True,
            )
            render_rule_clone({"name": name, "content": result})
        return result
    if kind == "tool":
        managed = {"description", "command", "url", "args", "env", "headers", "oauth"}
        metadata = metadata_with_extensions(metadata, extensions, managed)
        transport = fields.get("transport")
        if transport not in {"http", "stdio"}:
            raise ValueError("fields.transport must select http or stdio")
        if changed(paths, "transport"):
            for key in (
                {"url", "headers", "oauth"}
                if transport == "stdio"
                else {"command", "args", "env"}
            ):
                metadata.pop(key, None)
        for field in ("description", "command" if transport == "stdio" else "url"):
            if (
                changed(paths, field)
                or field not in metadata
                and field != "description"
            ):
                metadata[field] = text(
                    fields.get(field, ""),
                    "fields." + field,
                    required=validate and field != "description",
                    single_line=True,
                )
        if transport == "stdio":
            if changed(paths, "args"):
                metadata["args"] = strings(fields.get("args", []), "fields.args")
            if changed(paths, "env"):
                metadata["env"] = string_pairs(fields.get("env", []), "fields.env")
        else:
            if changed(paths, "headers"):
                metadata["headers"] = string_pairs(
                    fields.get("headers", []), "fields.headers", headers=True
                )
            oauth_extra = mapping(extensions.get("oauth", {}), "extensions.oauth")
            if "clientId" in oauth_extra:
                raise ValueError(
                    "extensions.oauth must not replace the managed client ID"
                )
            oauth = {
                **deepcopy(oauth_extra),
                **{
                    key: value
                    for key, value in metadata.get("oauth", {}).items()
                    if key == "clientId"
                },
            }
            if changed(paths, "oauth_client_id"):
                optional_text(
                    oauth,
                    "clientId",
                    fields.get("oauth_client_id", ""),
                    "fields.oauth_client_id",
                )
            if oauth or "oauth" in metadata:
                metadata["oauth"] = oauth
        if changed(paths, "notes"):
            result["body"] = text(fields.get("notes", ""), "fields.notes")
        if validate:
            validate_tool(metadata)
    elif kind == "hook":
        metadata = metadata_with_extensions(
            metadata, extensions, {"event", "matcher", "model", "hooks", "permissions"}
        )
        for field in ("event", "matcher"):
            if changed(paths, field):
                metadata[field] = text(
                    fields.get(field, ""),
                    "fields." + field,
                    required=validate and field == "event",
                    single_line=True,
                )
        if changed(paths, "handlers"):
            metadata["hooks"] = _handlers(fields.get("handlers", []))
        if changed(paths, "default_model"):
            optional_text(
                metadata,
                "model",
                fields.get("default_model", ""),
                "fields.default_model",
            )
        if changed(paths, "permissions"):
            rules = strings(fields.get("permissions", []), "fields.permissions")
            if rules:
                metadata["permissions"] = {"allow": rules}
            else:
                metadata.pop("permissions", None)
        if changed(paths, "notes"):
            result["body"] = text(fields.get("notes", ""), "fields.notes")
        if validate:
            validate_hook(metadata, agents)
    elif kind == "agent":
        metadata = metadata_with_extensions(
            metadata, extensions, {*AGENT_FIELDS.values(), "name"}
        )
        metadata["name"] = name
        for field, key in AGENT_FIELDS.items():
            if field == "tools":
                continue
            if changed(paths, field):
                if field in {"tools", "skills", "disallowed_tools"}:
                    metadata[key] = strings(fields.get(field, []), "fields." + field)
                else:
                    optional_text(
                        metadata, key, fields.get(field, ""), "fields." + field
                    )
        if changed(paths, "inherit_tools") or changed(paths, "tools"):
            inherit = fields.get("inherit_tools", not bool(fields.get("tools")))
            if not isinstance(inherit, bool):
                raise ValueError("fields.inherit_tools must be true or false")
            if inherit:
                metadata.pop("tools", None)
            else:
                metadata["tools"] = strings(fields.get("tools", []), "fields.tools")
        if changed(paths, "instructions"):
            result["body"] = text(
                fields.get("instructions"), "fields.instructions", required=validate
            )
        if validate:
            text(metadata.get("description", ""), "fields.description", required=True)
    else:
        raise ValueError("item_type is unsupported")
    result["metadata"] = metadata
    return result


def render_rule_clone(row):
    content = row["content"]
    description = content.get("metadata", {}).get("skill_description")
    if not description:
        return content["body"]
    try:
        header, instructions = split_document(content["body"])
    except UnsupportedDocument:
        raise ValueError(
            "fields.instructions contains unsupported legacy frontmatter; preserve or correct it in Raw"
        ) from None
    text(instructions, "fields.instructions", required=True)
    return compose_document(
        {
            "name": row["name"],
            "description": description,
            **{
                key: value
                for key, value in header.items()
                if key not in {"name", "description"}
            },
        },
        instructions,
    )


def prepare_rule_clone(name, content):
    fields, extensions = decode_other("rule", content)
    return compose_other(
        "rule",
        name,
        fields,
        extensions,
        content,
        ["/fields/clone_description"],
        clone_as_skill=True,
    )

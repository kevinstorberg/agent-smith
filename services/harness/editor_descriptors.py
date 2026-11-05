from __future__ import annotations


def additional_types(field):
    from services.api.models.hook import HOOK_EVENT_MAP

    def text(key, label, example, **settings):
        return field(key, label, "text", example, default="", **settings)

    def strings(key, label, example):
        return field(key, label, "strings", example, default=[])

    def pairs(key, label, key_label, key_example, value_example, **settings):
        return field(
            key,
            label,
            "pairs",
            key_example,
            default=[],
            fields=[
                text("key", key_label, key_example, required=True),
                text("value", "Value", value_example),
            ],
            **settings,
        )

    instructions = field(
        "instructions",
        "Instructions",
        "markdown",
        "Explain the complete task, constraints, context and expected result.",
        default="",
        required=True,
    )
    notes = field(
        "notes",
        "Notes",
        "markdown",
        "Optional notes about this integration.",
        default="",
    )
    return {
        "rule": {
            "label": "Rule",
            "initial_extensions": {"metadata": {}},
            "common_fields": [
                field(
                    "clone_as_skill",
                    "Publish as a skill",
                    "boolean",
                    "Also publish these instructions as a skill artifact",
                    default=False,
                )
            ],
            "fields": [
                instructions,
                text(
                    "clone_description",
                    "Skill description / when to use",
                    "Use when reviewing application changes.",
                    required=True,
                    when={"clone_as_skill": "true"},
                ),
            ],
        },
        "tool": {
            "label": "Tool",
            "initial_extensions": {"metadata": {}, "oauth": {}},
            "fields": [
                field(
                    "transport",
                    "Connection type",
                    "select",
                    "HTTP or a local command",
                    choices=["http", "stdio"],
                    default="http",
                    required=True,
                ),
                text(
                    "description", "Description", "Local repository maintenance tools"
                ),
                text(
                    "url",
                    "Server URL",
                    "https://example.com/mcp or ${MCP_BASE}/mcp",
                    required=True,
                    when={"transport": "http"},
                ),
                text(
                    "command",
                    "Executable",
                    "${AGENT_SMITH_ROOT}/.venv/bin/python",
                    required=True,
                    when={"transport": "stdio"},
                ),
                field(
                    "args",
                    "Arguments",
                    "strings",
                    "--config (enter one argument per row)",
                    default=[],
                    when={"transport": "stdio"},
                ),
                pairs(
                    "env",
                    "Environment variables",
                    "Variable",
                    "API_TOKEN",
                    "${API_TOKEN}",
                    when={"transport": "stdio"},
                ),
                pairs(
                    "headers",
                    "HTTP headers",
                    "Header",
                    "Authorization",
                    "Bearer ${API_TOKEN}",
                    when={"transport": "http"},
                ),
                text(
                    "oauth_client_id",
                    "OAuth client ID",
                    "my-client-id",
                    when={"transport": "http"},
                ),
                notes,
            ],
        },
        "hook": {
            "label": "Hook",
            "initial_extensions": {"metadata": {}},
            "fields": [
                field(
                    "event",
                    "When to run",
                    "select",
                    "pre_tool_use",
                    choices=sorted(
                        set().union(
                            *(set(events) for events in HOOK_EVENT_MAP.values())
                        )
                    ),
                    default="pre_tool_use",
                    required=True,
                ),
                text("matcher", "Tool matcher", "Bash|Edit|Write"),
                text(
                    "default_model", "Default model for AI handlers", "haiku (optional)"
                ),
                field(
                    "handlers",
                    "Handlers",
                    "rows",
                    "Add a command, prompt, or agent handler",
                    default=[],
                    fields=[
                        field(
                            "type",
                            "Handler type",
                            "select",
                            "command",
                            choices=["command", "prompt", "agent"],
                            default="command",
                            required=True,
                        ),
                        text(
                            "command",
                            "Command",
                            "python /absolute/path/check.py",
                            required=True,
                            when={"type": "command"},
                        ),
                        field(
                            "prompt",
                            "Prompt",
                            "markdown",
                            "Review the complete tool input and explain whether it should proceed.",
                            default="",
                            required=True,
                            when={"type": ["prompt", "agent"]},
                        ),
                        text(
                            "model",
                            "Handler model override",
                            "haiku (uses default when empty)",
                            when={"type": ["prompt", "agent"]},
                        ),
                        field(
                            "timeout",
                            "Timeout in seconds",
                            "number",
                            "30",
                            default=None,
                            minimum=0.001,
                        ),
                        field(
                            "async",
                            "Run command asynchronously",
                            "boolean",
                            "Allow this command to continue without blocking",
                            default=False,
                            when={"type": "command"},
                        ),
                        field(
                            "settings",
                            "Additional handler settings",
                            "json",
                            "Optional handler-specific settings",
                            default={},
                        ),
                    ],
                ),
                strings(
                    "permissions",
                    "Allowed tool permissions",
                    "mcp__memory__memory_search",
                ),
                notes,
            ],
        },
        "agent": {
            "label": "Agent",
            "initial_extensions": {"metadata": {}},
            "fields": [
                text(
                    "description",
                    "Description / when to use",
                    "Reviews changes for correctness and security",
                    required=True,
                ),
                instructions,
                text("model", "Model", "sonnet (leave empty to inherit)"),
                field(
                    "inherit_tools",
                    "Use inherited tools",
                    "boolean",
                    "Use the parent agent's tools",
                    default=True,
                ),
                {
                    **strings("tools", "Allowed tools", "Read"),
                    "when": {"inherit_tools": "false"},
                },
                strings("disallowed_tools", "Disallowed tools", "Bash"),
                strings("skills", "Skills", "review_changes"),
            ],
        },
    }

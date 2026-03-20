---
name: load
description: >
  List all rules, skills, and MCP tools currently available to this agent.
  Use when asked "what can you do", "what tools do you have", or "show your capabilities".
---

List everything you currently have access to, grouped into three sections:

1. **Rules**: List each behavioral rule by its heading (e.g. "Design by Contract",
   "DRY", "Tracer Bullets"). These come from your rules/instructions file.

2. **Skills**: List each available slash command with its name and one-line description
   (e.g. `/commit`, `/iterate`, `/memory`). Include this skill.

3. **MCP Tools**: List each connected MCP server by name and its connection status
   (connected or failed). Note any servers that require authentication.

Format as a clean numbered list under each heading. Do not explain what each item does
in detail unless asked.

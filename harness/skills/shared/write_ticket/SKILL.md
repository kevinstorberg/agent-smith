---
name: write_ticket
description: >
  Standard Jira ticket structure. Use when creating any Jira ticket, regardless of type
  (Bug, Task, Story). Other skills that create tickets should reference this skill for
  the description format.
---

ALL Jira ticket descriptions MUST use this structure:

```markdown
# Story
<one-sentence narrative of the work from the user's or developer's perspective>

# Objective
<what this ticket aims to accomplish and why it matters>

## Summary
<concise description of the problem, request, or feature>

## Tasks
- [ ] <actionable task 1>
- [ ] <actionable task 2>
- [ ] <additional tasks as needed>

# Context
<relevant details: error messages, links, steps to reproduce, affected users,
who reported it, any discussion or decisions made>

# Out of Scope
<anything explicitly excluded or deferred; write "N/A" if nothing is out of scope>
```

When creating a ticket, fill in every section. Do not skip sections. Do not reorder them.

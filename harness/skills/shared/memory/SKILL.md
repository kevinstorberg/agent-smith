---
name: memory
description: >
  Search long-term memory for context before starting work or making decisions.
  Store key learnings after completing work. MUST be used at the start of every
  session, every plan, and after every completed task.
---

1. **Recall** (always TWO searches):
   - `memory_search(query="<topic>", repo="<current-repo>")` for project knowledge.
   - `memory_search(query="<topic>")` (no repo) for general knowledge.
   - Summarize relevant findings before proceeding.

2. **Work**: Complete the task using recalled context.

3. **Store** (choose the right scope):
   - **Project-specific** (repo patterns, conventions, decisions):
     `memory_add(content="...", repo="<current-repo>", tags=[...])`
   - **General** (engineering principles, cross-project patterns):
     `memory_add(content="...", tags=[...])` (no repo)
   - Always include descriptive tags.

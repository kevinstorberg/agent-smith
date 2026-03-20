## Long-Term Memory

You have access to a persistent memory system via MCP tools. You MUST use it actively.

### When to search (MANDATORY)

Search memory at each of these points. Do not skip this step.

1. **Start of every session** before doing any work.
2. **Start of every plan** before proposing an approach.
3. **Before any significant decision** (architecture, library choice, pattern selection).

Always run TWO searches to avoid missing context:
- `memory_search(query="<topic>", repo="<current-repo>")` for project-specific knowledge.
- `memory_search(query="<topic>")` (no repo) for general engineering principles and cross-project learnings.

Briefly summarize relevant findings before proceeding.

### When to store (MANDATORY)

Store a memory at each of these points. Do not skip this step.

1. **After completing a plan or task** that involved non-trivial decisions.
2. **After making an architectural or design decision** and the rationale behind it.
3. **After solving a non-obvious problem** that a future session should know about.
4. **After discovering a project-specific pattern** or convention.

### Scoping

- **Project-specific** knowledge (codebase patterns, project conventions, repo-specific decisions):
  set `repo` to the current repo/project name.
- **General** knowledge (engineering principles, tool preferences, cross-project patterns):
  leave `repo` empty so it surfaces in every unscoped search.

### Tags

Always include descriptive tags for filtering. Use short, lowercase labels:
`["architecture", "auth", "testing", "debugging", "convention", "decision"]`

### Example

```
# Start of session: dual search
memory_search(query="auth patterns", repo="my-app")
memory_search(query="auth patterns")

# ... do work ...

# Project-specific learning
memory_add(content="my-app uses httpOnly cookies for refresh tokens, 1h JWT expiry",
           repo="my-app", tags=["auth", "security"])

# General principle (no repo)
memory_add(content="Always validate JWT signature before checking claims to fail fast",
           tags=["auth", "security", "convention"])
```

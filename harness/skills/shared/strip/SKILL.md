---
name: strip
description: >
  Search code for comments, docstrings, and inline documentation that are outdated,
  redundant, or overly verbose. Use when asked to "clean up comments", "strip docs",
  or "remove unnecessary documentation".
---

1. **Scan**: Read through the files in scope. Flag:
   - Comments that restate what the code already says (e.g. `x = x + 1  # increment x`)
   - Docstrings that describe the "how" instead of the "why"
   - Outdated comments that no longer match the code they describe
   - TODO/FIXME comments for work that has already been done
   - Boilerplate or auto-generated docstrings that add no value
   - Type annotations repeated in both code and docstring

2. **Catalogue**: Present a numbered list of every flagged item with:
   - File path and line number
   - The offending text
   - Why it should be removed or rewritten (outdated, redundant, or verbose)

3. **Align**: Stop and wait for the user to approve removals or rewrites.

4. **Clean**: Remove or rewrite each approved item. Comments that explain *why*
   a decision was made should be kept. Comments that explain *what* the code does
   should be removed if the code is self-explanatory.

5. **Verify**: Run existing tests to confirm nothing broke.

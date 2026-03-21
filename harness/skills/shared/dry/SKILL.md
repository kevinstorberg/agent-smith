---
name: dry
description: >
  Search the codebase for opportunities to DRY up and modularize code. Use when
  asked to "clean up", "reduce duplication", "modularize", or "DRY up the code".
---

1. **Scan**: Read through the files in scope (current directory, specified files, or
   the full codebase if asked). Look for:
   - Repeated logic that appears in two or more places
   - Copy-pasted code with minor variations
   - Functions or methods that do multiple unrelated things
   - Inline logic that could be extracted into a named function
   - Constants or magic values repeated across files

2. **Catalogue**: Present a numbered list of every duplication or modularization
   opportunity found. For each item, state:
   - Where the duplication exists (file paths and line numbers)
   - What the repeated logic does
   - How severe it is (will it cause bugs if one copy is updated but not the other?)

3. **Align**: Stop and wait for the user to select which items to address.

4. **Refactor**: For each approved item, extract the shared logic into a single
   authoritative location. Ensure all call sites reference the new abstraction.
   Do not change behavior.

5. **Verify**: Run existing tests to confirm nothing broke.

---
name: pr
description: Create a pull request with a clear title and description. Use when asked to "open a PR", "create a pull request", or "submit for review".
---

1. Review branch changes: `git log origin/main..HEAD --oneline` and `git diff origin/main...HEAD --stat`.
2. Draft a PR title (≤ 70 chars) and a body with:
   - **Summary**: what changed and why
   - **Changes**: bullet list of notable modifications
   - **Test plan**: what was tested / how to verify
3. Run: `gh pr create --title "…" --body "…"`
4. Report the PR URL.

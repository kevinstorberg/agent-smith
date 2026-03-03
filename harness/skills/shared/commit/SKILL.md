---
name: commit
description: Stage all changes, commit with a descriptive conventional message, and push to origin. Use when asked to "commit", "save changes", "create a commit", or "push".
---

1. Run `git status` and `git diff` to understand what changed.
2. Stage all relevant changes (`git add -A`, or selectively as appropriate).
3. Write a commit message: `<type>(<scope>): <summary>`
   Valid types: feat, fix, refactor, chore, docs, test, style, perf.
   Summary ≤ 72 characters. Add a body paragraph explaining *why* if the change needs context.
4. Commit and report the resulting hash.
5. Push to origin: `git push origin HEAD`.

Never commit secrets, credentials, or `.env` files.

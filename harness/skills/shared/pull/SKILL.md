---
name: pull
description: Pull the latest changes from origin for the current branch. Use when asked to "pull", "sync from origin", or "get the latest".
---

1. Run `git status` to confirm there are no uncommitted changes that could cause conflicts.
   If there are, stop and ask the user how to handle them before proceeding.
2. Pull: `git pull origin HEAD`.
3. Report what changed (commits pulled, files affected) or confirm already up to date.

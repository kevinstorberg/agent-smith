---
name: explore
description: >
  Systematically explore and explain an unfamiliar codebase. Use when asked to
  "explore this repo", "what does this codebase do", "walk me through this project",
  or "help me understand this code". This skill is read-only — it never edits files.
---

1. **Orient**: Read the repo's identity files to establish context fast.
   - README, LICENSE, and the primary manifest (package.json, pyproject.toml,
     Gemfile, Cargo.toml, go.mod, pom.xml — whichever exists).
   - Top-level directory listing.
   - Goal: determine the project name, language, framework, and stated purpose.

2. **Map**: Build a structural overview of the repository.
   - List each top-level directory with a one-line description of its purpose.
   - Identify entry points (main files, CLI scripts, route definitions, app bootstrap).
   - Identify configuration (CI, Docker, linter configs, infra-as-code).
   - Summarize the language breakdown by counting file types.

3. **Analyze**: Read representative files to understand the architecture.
   - Identify the key abstractions (core classes, modules, or interfaces)
     and what domain concept each represents.
   - Trace the primary data/request flow end-to-end through the system.
   - Read the test directory to understand testing patterns and coverage approach.
   - Check the dependency manifest for notable libraries and what role each plays.
   - Identify the architectural pattern (MVC, event-driven, pipeline, monolith,
     microservices, etc.).

4. **Present**: Output a structured report with these sections. Use headings so the
   user can scan and reference it later.
   - **Purpose**: What the project does and who it serves (one paragraph).
   - **Tech Stack**: Language, framework, key dependencies.
   - **Architecture**: How components relate — use a short text diagram if helpful.
   - **Directory Map**: Top-level tree with one-line descriptions.
   - **Key Abstractions**: The most important types/modules and their roles.
   - **Entry Points**: How the application starts and how users interact with it.
   - **Testing**: Test framework, patterns, and how to run tests.
   - **Development Setup**: How to install, build, and run locally.

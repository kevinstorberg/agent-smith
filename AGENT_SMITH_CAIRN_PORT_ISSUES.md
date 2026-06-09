# Agent Smith Cairn Port Inventory

## Run Metadata

- Started: 2026-06-05T20:21:37Z
- Cairn source branch: master
- Cairn source commit: 5ebe661
- Validation branch: agent-smith-cairn-port-validation
- Validation worktree: .claude/worktrees/agent-smith-cairn-port-validation
- Agent Smith source repo: /Users/kstorberg/sondermind/agent-smith
- Agent Smith source commit: 261e829
- Agent Smith source status: read-only; existing modified file docs/erd.png
- API port: 18031
- Frontend port: 15183
- Postgres host port: 55434
- Redis host port: 56384
- Production Postgres mode: read-only only
- Production vector-store mode: read-only only
- Production mutations: prohibited during this validation
- Production-grade port pass completed: 2026-06-08
- Cleanup status: Uvicorn stopped; Docker Postgres/Redis containers and compose network removed

## Data-Safety Ledger

| Boundary | Mode | Evidence | Status |
| --- | --- | --- | --- |
| Cairn master | no edits | worktree created from master | pass |
| Agent Smith source repo | read-only | source status recorded; no writes planned | pass |
| Local/shadow database | write-capable | local Docker Postgres at `7c1f9a2b3d4e`; expected tables present | pass |
| Production Postgres | read-only | `AGENT_SMITH_PROD_DATABASE_URL_READONLY` not present | expected local limitation |
| Production vector store | read-only | `PINECONE_API_KEY`/`PINECONE_INDEX` not present | expected local limitation |
| Agent config sync targets | sandbox-only | `/api/harness/sync` wrote under `tmp/agent-smith-sync-sandbox` | pass |
| Real ~/.claude ~/.codex ~/.gemini | no writes | sync sandbox override active; no real-home target used | pass |
| Runtime cleanup | local services stopped | no Uvicorn process; `docker compose ps` returned no running services | pass |

## Source Contract Inventory

### HTTP Routes

- `/api/harness/rules`, `/api/harness/skills`, `/api/harness/mcp`, `/api/harness/hooks`, `/api/harness/agents`
- `/api/harness/items/{rule|skill|tool|hook|agent}` list/create
- `/api/harness/items/{type}/reorder`
- `/api/harness/items/{type}/{item_id}` get/patch/delete
- `/api/harness/items/{type}/{item_id}/content`
- `/api/harness/items/{type}/{item_id}/history`
- `/api/harness/items/{type}/{item_id}/configs` create
- `/api/harness/items/{type}/{item_id}/configs/{config_id}` patch/delete
- `/api/harness/sync`, `/api/harness/unsync`, `/api/harness/sync/{item_type}/{item_id}`
- `/api/memory/search`, `/api/memory/list`, `/api/memory/{memory_id}` get/update/delete
- `/api/evals`, `/api/evals/categories`, `/api/evals/subcategories`, `/api/evals/chart`, `/api/evals/chart/average`, `/api/evals/{eval_id}` get/delete
- `/api/plans`, `/api/plans/search`, `/api/plans/{plan_id}` get/update/delete
- `/api/jobs`, `/api/jobs/{job_id}`, `/api/jobs/{job_id}/run-now`
- `/api/jobs/{job_id}/executions`, `/api/jobs/{job_id}/executions/{execution_id}`
- `/api/jobs/{job_id}/configs`, `/api/jobs/{job_id}/configs/{config_id}`
- `/api/eval-configs/suites`, `/api/eval-configs/suites/{suite_id}`
- `/api/eval-configs/suites/{suite_id}/scenarios`, `/api/eval-configs/scenarios/{scenario_id}`

### MCP Tools

- `/mcp/memory`: `memory_add`, `memory_search`, `memory_list`, `memory_delete`, `memory_update`
- `/mcp/plans`: `save`, `get`
- `/mcp/harness`: `harness_list`, `harness_get`, `harness_upsert`, `harness_disable`, `harness_sync_item`
- `/mcp/evals`: eval suite/scenario management tools
- `/mcp/graphs`: `run_graph`
- `/mcp/jobs`: `job_create`, `job_list`, `job_get`, `job_update`, `job_delete`, `job_run_now`, execution/config tools

### Database And Migrations

- Agent Smith revisions copied into Cairn migration path:
  - `c4f4597bb8a2_create_harness_tables`
  - `6ca1bae4f560_add_versioning_constraints`
  - `e1f2a3b4c5d6_create_harness_agents_and_subagents`
  - `f2a3b4c5d6e7_create_harness_configs`
  - `25243649fc8e_create_plans_table`
  - `c5d6e7f8a9b0_create_eval_suites_and_scenarios`
  - `a1b2c3d4e5f6_add_eval_subcategory`
  - `b3c4d5e6f7a8_add_eval_prompt`
  - `7566da429faa_create_eval_results_table`
  - `23f8a4d0e4b0_create_background_jobs_tables`
  - `7c1f9a2b3d4e_add_device_to_job_executions`
  - `a2b3c4d5e6f7_add_clone_as_skill`
  - `b4c5d6e7f8a9_sort_key_to_integer`
- Tables: harness item tables, harness_configs, plans, eval_suites, eval_scenarios, eval_results, background_jobs, job_configs, job_executions.
- Safety requirement: local/shadow migrations only during this validation.

### Frontend Routes And Workflows

- Root dashboard redirects to `/harness/rules`.
- Harness pages: rules, skills, tools, hooks, agents, create, detail/edit/config/history.
- Memory page: list/search/update/delete.
- Evals pages: list/detail/charts/categories/subcategories.
- Plans pages: list/create/detail/edit/delete.
- Jobs pages: list/create/detail/edit/run-now/executions/configs.
- Eval config pages: suites/scenarios CRUD.

### Scripts

- `scripts/sync.py`: sync harness items to agent config targets.
- `scripts/reverse_sync.py`: import rules/skills/tools from agent config targets.
- `scripts/memory.py`: local memory CLI.
- `scripts/plans.py`: local plans CLI.
- Safety requirement: sync/reverse-sync must use `AGENT_SMITH_SYNC_ROOT` sandbox during validation.

### Jobs

- Background jobs are DB-backed shell commands with interval `schedule_config`.
- Agent Smith legacy scheduler records `job_executions`, handles timeout/failure/interrupted, and scopes by `job_configs`.
- Safety requirement: scheduler enabled only for local/shadow DB during validation.

### Evals

- Eval suites/scenarios/results are stored in Postgres.
- DeepEval/G-Eval provider execution is credential-gated.
- Local parity validates DB/API/MCP behavior without requiring live LLM judging.

### Vector Memory

- Local backend: LanceDB under `MEMORY_STORE_PATH`.
- Production backend: Pinecone via `PINECONE_API_KEY` and `PINECONE_INDEX`.
- Safety requirement: production vector validation is describe/query/fetch only; no create/delete/write.

## Coverage Matrix

| Feature | Manual trigger | Expected | Actual | Evidence | Status |
| --- | --- | --- | --- | --- | --- |
| Worktree baseline | `git worktree add ...` | isolated branch/worktree exists | worktree created | branch agent-smith-cairn-port-validation at 5ebe661 | pass |
| Source contract inventory | read-only `rg`/`find` inspection | route/tool/schema/frontend/script matrix captured | captured initial matrix | this file | pass |
| Local migrations | `poetry run alembic upgrade head` | Agent Smith revision chain applies locally | upgraded to `7c1f9a2b3d4e` | Alembic output and psql schema inspection | pass |
| Live app startup | `poetry run uvicorn src.app:app --host 127.0.0.1 --port 18031` | Cairn app starts with Agent Smith routes/MCP/runtime | startup clean | Uvicorn logs show six MCP session managers and app startup complete | pass |
| Health route | `curl /health` | configured app identity returned | `agent-smith-cairn-port` | `{\"status\":\"ok\",\"app\":\"agent-smith-cairn-port\"...}` | pass |
| Harness seed/list | `curl /api/harness/mcp` | seeded MCP tool entries returned | 6 MCP entries returned | memory/plans/harness/evals/graphs/jobs URLs | pass |
| Plans API | POST `/api/plans` | create plan in local DB | plan id 1 created | response returned title/body/project timestamps | pass |
| Harness API | POST `/api/harness/items/rule` | create rule and default config | rule id 1 created | response includes config id 7 and agents | pass |
| Scheduled job | create 2-second interval job | scheduler fires and records executions | job fired repeatedly | `/api/jobs/1/executions`, DB status counts, `tmp/agent-smith-job.log` | pass |
| Sync sandbox | POST `/api/harness/sync` | sync writes only to sandbox | wrote Claude/Codex/Gemini files under worktree tmp | `tmp/agent-smith-sync-sandbox` file list | pass |
| Frontend check | `npm --prefix frontend run check` | lint, tests, and build pass | 25 test files / 254 tests passed; build succeeded | npm output | pass |
| Static frontend | curl `/`, `/harness/rules`, JS asset, logo asset | backend serves built SPA and assets | all returned 200 | root/index HTML, route fallback, JS size 2247633, logo size 11840 | pass |
| Memory local | `scripts.memory add/search` and `/api/memory/list` | local LanceDB memory add/search/list works | memory id `836ccc5c-bdb7-4321-ae18-0ad0682355e3` stored and found | CLI and HTTP output | pass |
| MCP memory | streamable HTTP initialize + `tools/list` | `/mcp/memory/` exposes memory tools | initialize 200 and tools listed | `memory_add/search/list/delete/update` returned | pass |
| Graph runtime | `dispatch("echo", {"text": "cairn port"})` | built-in graph returns deterministic result | returned `cairn port` | Python command output | pass |
| Eval config API | POST suite and scenario | eval suite/scenario CRUD works locally | suite id 1 and scenario id 1 created | API responses | pass |
| Cairn-shaped plans slice | `/api/plans` list/create/search | plans use repository/service/UoW and preserve wire shape | list/create/search passed | plan id 2 created via new router | pass |
| Agent Smith opt-in isolation | `APP_ENV=test poetry run pytest tests/api/test_errors.py tests/app/test_lifespan.py tests/diagnostics/test_router.py -q` | Cairn base tests should not mount Agent Smith SPA or seed runtime | 17 passed | added `AGENT_SMITH_ENABLED=false` default and enabled only in `.env.development` | pass |
| Backend hygiene | `poetry check --lock`, `poetry run ruff check .`, `poetry run ruff format --check .` | backend metadata, lint, and formatting pass | all passed after mechanical Ruff cleanup | command output | pass |
| Full template check | `make check` | backend tests and frontend checks pass | 448 backend tests passed; 25 frontend test files / 254 tests passed; frontend build succeeded | command output | pass |
| Pre-commit | `make pre-commit` | repository hooks pass without modifying files | ruff, ruff-format, whitespace, EOF, YAML, large-file, private-key hooks passed | command output | pass |
| Backend audit | `make audit` | Python dependency audit passes | `No known vulnerabilities found` | command output | pass |
| Frontend audit | `npm --prefix frontend audit --audit-level=high` | no high-severity frontend dependency findings | `found 0 vulnerabilities` | npm audit output after dependency upgrade | pass |
| Production credentials | inspect explicit env vars | do not use unrelated production credentials | Agent Smith-specific prod DB/vector creds absent | env check | expected local limitation |
| Production preflight script | `poetry run python scripts/agent_smith_preflight.py` | local/shadow preflight records migration head and row counts | passed against local DB at head `7c1f9a2b3d4e` | script output with Agent Smith table counts | pass |
| Legacy runtime static gate | `rg "psycopg2|get_connection|services\.api\.models|services\.jobs\.models" src scripts services -g '*.py'` | no production Python runtime usages | no matches | command returned no output | pass |
| Cairn-shaped domains | inspect `src/agent_smith/repositories`, `src/agent_smith/services`, routers, MCP servers | harness, evals, jobs, memory, sync, graphs, and plans use Cairn service/repository/runtime seams | ported and wired through shared services | live HTTP/MCP/job/sync checks plus static gate | pass |

## Confirmed Issues

No open confirmed issues remain from the validation inventory after the production-grade port pass. Production DB/vector read-only validation is still an expected local limitation until the explicit production read-only credentials are provided.

## Resolved Issues

### ASCP-001: Copied Agent Smith frontend dependencies report vulnerabilities

- Severity: medium
- Area: frontend/security automation
- Reproduction: `npm --prefix frontend audit --audit-level=high`
- Expected: frontend dependency install completes without high-severity audit findings
- Actual before fix: audit reported high-severity advisories in `react-router` and `vite`
- Resolution: upgraded frontend dependencies and refreshed `package-lock.json`
- Evidence: `npm --prefix frontend audit --audit-level=high` returned `found 0 vulnerabilities`
- Impact: frontend dependency baseline no longer blocks production-readiness
- Status: resolved

### ASCP-002: Most copied Agent Smith domains still use legacy raw SQL paths

- Severity: high
- Area: architecture/maintainability
- Reproduction: inspect copied modules and run static legacy-runtime gate
- Expected: production candidate should consistently use Cairn SQLAlchemy models, repositories, services, and UnitOfWork boundaries
- Actual before fix: only `/api/plans` used Cairn repository/service/UoW; harness, evals, jobs, sync, and memory still depended on copied raw psycopg2 model functions
- Resolution: moved harness, evals, jobs, memory, sync, graph dispatch, MCP servers, and scripts behind `src.agent_smith` repositories/services/runtime adapters; removed legacy app/model/runtime artifacts from production paths
- Evidence: `rg "psycopg2|get_connection|services\.api\.models|services\.jobs\.models" src scripts services -g '*.py'` returned no matches; live HTTP/job/sync/memory checks passed
- Impact: Agent Smith now follows Cairn’s opinionated maintainable structure rather than a copied legacy runtime
- Status: resolved

## Pain Points

- Python runtime range had to be tightened to `>=3.11,<3.14` because `langchain-pinecone` does not currently support Python 3.14. This is acceptable for a production Agent Smith port, but it should be documented before cutover.
- Cairn's previous optional `pinecone-client` dependency overlaps with Agent Smith's modern `pinecone` package at the import-module level. The validation worktree now uses `pinecone` for the Pinecone optional group to avoid overlapping distributions.
- First `src.app` import took roughly 20 seconds while Agent Smith MCP/memory imports loaded LangChain/ML dependencies. This does not block functionality, but production boot should lazy-load embedding-heavy paths where practical.
- Frontend production build still has a large lazy editor/vendor chunk, but the main app chunk is split down to roughly 245 kB before gzip and the build no longer warns at the configured threshold.
- Memory add/search emits an unauthenticated Hugging Face Hub warning. Production should either pre-cache the embedding model in the image/volume or configure `HF_TOKEN` for reliable startup.
- Agent Smith runtime and root SPA fallback must remain explicitly opt-in. Before `AGENT_SMITH_ENABLED` was added, Cairn's `APP_ENV=test` suite saw HTML SPA fallback responses for unknown test routes and lifespan startup attempted legacy Agent Smith DB seeding.

## Resolved During Validation

- Made Agent Smith integration opt-in with `AGENT_SMITH_ENABLED=false` by default and `AGENT_SMITH_ENABLED=true` only in validation `.env.development`. This preserves Cairn API-only behavior and keeps test/CI environments from mounting the Agent Smith SPA fallback, MCP routes, or legacy scheduler unless explicitly enabled.
- Fixed sync subprocess execution to use `python -m scripts.sync`, avoiding stdlib `inspect` shadowing from `scripts/inspect.py`.
- Routed sync outputs through `AGENT_SMITH_SYNC_ROOT`, including subprocess settings reads, so sync/reverse-sync validation remains sandboxable.

## Works As Expected

- Cairn master was clean before creating the validation worktree.
- The validation worktree was created without touching Cairn master.
- Agent Smith was inspected as read-only and its existing modified `docs/erd.png` was preserved.
- `poetry run python -c 'import src.app; print("import-ok")'` completed successfully after dependency installation.
- Local Postgres/Redis started on ports 55434/56384 and local schema contains the expected Agent Smith tables.
- Real local scheduled job fired and recorded successful `job_executions`; the local smoke job was deleted after validation to stop further side effects.
- Harness sync wrote only into the validation sandbox: `.claude`, `.codex`, and `.gemini` outputs were created under `tmp/agent-smith-sync-sandbox`.
- Agent Smith frontend lint/tests/build passed after removing stale Cairn scaffold files.
- Built Agent Smith SPA is served by the backend at root routes with request IDs/security headers.
- Local LanceDB vector memory add/search/list worked with the configured embedding model.
- MCP streamable HTTP initialized successfully for `/mcp/memory/` and returned the expected memory tool schemas.
- Agent Smith graph runtime dispatch worked for the built-in `echo` graph.
- Eval suite/scenario configuration APIs worked locally without live LLM credentials.
- The plans domain now has a Cairn-shaped repository/service/UoW implementation while preserving Agent Smith API behavior.
- `make check` passed: 448 backend tests, frontend lint, 25 frontend test files / 254 tests, and frontend build.
- `make pre-commit` passed all hooks.
- `make audit` passed for Python dependencies.
- `npm --prefix frontend audit --audit-level=high` passed with no vulnerabilities.
- Static legacy-runtime gate found no `psycopg2`, `get_connection`, or legacy model package production Python usages.
- Local Agent Smith production preflight script passed against the shadow DB and recorded migration head/table counts.
- `git diff --check` passed.

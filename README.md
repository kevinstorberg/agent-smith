<img src="assets/agent_smith_logo_white_thick.svg" alt="AgentSmith" width="120" align="left" style="margin-right: 20px; margin-bottom: 10px;"/>

# agent-smith

A single harness for managing rules, skills, and MCP servers across multiple AI coding agents.
One source of truth, synced everywhere.

## Quick Start

```sh
./setup.sh                   # once: Python + frontend dependencies
./run.sh
```

Requires Python 3.13 and Node 22.12 or newer. `./setup.sh` installs into `.venv`
and `services/client/node_modules`; subsequent launches reuse those dependencies.
`./run.sh` starts production: it builds the frontend only when source inputs change,
then serves the dashboard + API + MCP on port 7654. If this checkout's instance of the
same mode is already running, `./run.sh` gracefully stops it first and relaunches; a
launch whose configuration fails validation leaves the running instance untouched.
Generate the ERD separately with `./erd.sh` (requires native Graphviz).

```sh
./run.sh dev                 # API with reload on 7655, Vite UI on 4321
./run.sh -d                  # production in the background (restarts it if running)
./run.sh --status            # inspect production process
./run.sh --stop              # graceful shutdown of this checkout's production process
./run.sh dev --stop          # stop development
./run.sh -nc                 # force frontend rebuild; also accepts --rebuild
```

Launch modes select `.env.development` and `.env.production` respectively. Override
ports with `DASHBOARD_PORT` and `DEV_FRONTEND_PORT`. Servers bind to loopback by
default; set `DASHBOARD_HOST` explicitly for remote access. Background launch reports
that startup has begun; inspect `.runtime/<environment>.log` for readiness/failures.
Use separate checkouts for active development and production so dependency refreshes
and frontend builds cannot alter the deployed checkout.

Typed resource searches and text filters request automatically after a 300ms pause,
including Rules, Plans, Meetings, Profiles, Memory and person pickers. Select and checkbox
filters apply immediately. Changing criteria returns to the first page and ignores late
responses from earlier searches.

Agents connect to individual MCP endpoints at
`http://localhost:<DASHBOARD_PORT>/mcp/<server>/`, such as `/mcp/memory/`.
Tool requests use POST with `Accept: application/json, text/event-stream`.
Optional GET event streams require `Accept: text/event-stream`; requests without it
receive 406. The local servers do not require OAuth, so unsupported discovery URLs
under `/.well-known/` return 404. Expected OAuth/OpenID discovery probes and GET requests
without the SSE Accept header on unauthenticated MCP endpoints are recorded at DEBUG level;
their HTTP responses are unchanged. Other 404s, 406 failures, warnings and errors remain visible. Routine stateless transport
cleanup messages are quieted.

## Structure

```text
assets/              # static assets (images, etc.)
docs/                # generated artifacts (ERD, etc.)
evals/               # LLM-as-judge evaluation framework (DeepEval + G-Eval)
scripts/             # sync, generation, and shared utilities
services/
  api/               # FastAPI app, routers, models, validators
  chat/              # shared Chat Rooms service and agent MCP tools
  client/            # React dashboard (Vite + TypeScript)
  db/                # Postgres connection + Alembic migrations
  memory/            # vector memory + MCP tools (pgvector, LanceDB, or Pinecone)
```

## Harness

Rules, skills, tools, hooks, and sub-agents are stored in Postgres with versioning and
per-agent assignment. Each item has one or more **deployment configs** (`harness_configs`)
that control where it syncs — scoped by device (`DEVICE_NAME`) and repo (absolute path).
Configs can be additive (include) or subtractive (exclude). Managed via the dashboard UI
or MCP tools.

## Sync

```sh
./sync.sh
```

Reads harness items from the database, resolves deployment configs, and writes to each
agent's config files — globally (`~/.claude/`, `~/.codex/`, `~/.gemini/`) or per-repo
(e.g., `<repo>/.claude/rules/`).

- **compose** — concatenates rules into a single markdown file
- **copy** — syncs skill subdirectories to the agent's skills directory
- **merge** — merges MCP server configs into the agent's settings file
- **agents** — syncs sub-agent definitions as markdown files with YAML frontmatter

Supports Claude, Codex, and Gemini. Only writes when content has changed. Set
`DEVICE_NAME` in your environment's `.env.*` file to enable device-scoped filtering.

## Memory

Vector memory with time-weighted retrieval, served as MCP tools on the dashboard endpoint.
Meeting-generated memories join this same reusable store and remain available to other agents.
On **Memory**, enable **Meetings only** to filter by meeting provenance without changing the
records' tags or creating another store. The list/search API accepts `meeting_only=true`;
returned records include `from_meeting`, `source_type` and `source_id` when known.
New meeting memories carry useful topic tags such as `product`, `paralign` and `security`.
Meeting origin is separate from tags. Legacy origin tags are hidden on reads without
rewriting old memories or rerunning their meetings. Agents can use `tags` and
`meeting_only` on both MCP `memory_search` and `memory_list`, for example
`memory_search(query="MFA follow-up", tags=["security"], meeting_only=True)`.
Defaults to LanceDB (local, stored in `memory_store/`). The supported backends are
`lancedb`, `pinecone`, and `pgvector`. The pgvector backend uses the existing
`DATABASE_URL_<ENV>` database and the Alembic-managed `memories` table:

```env
MEMORY_BACKEND=pgvector
MEMORY_EMBEDDING_MODEL=all-MiniLM-L6-v2
MEMORY_EMBEDDING_DIMENSION=384
MEMORY_EMBEDDING_DEVICE=cpu
```

Embedding initialization and encoding are serialized. CPU is the default to avoid
concurrent native MPS model/device initialization on macOS. An explicit
`MEMORY_EMBEDDING_DEVICE` overrides it without changing the stored model or dimensions.

The model and dimension form one storage contract. Changing either requires a schema and
data migration; startup fails if stored rows use a different model or the database column
has a different dimension. pgvector retrieval uses exact cosine distance, so no approximate
index needs to be trained before cutover. Keep `MEMORY_BACKEND=pinecone` during the data
migration and change the production backend only after reconciliation passes.

## Background Jobs

Shell commands and LangGraph workflows run on a fixed interval, managed via the dashboard
(the **Jobs** tab) or MCP tools. Each job stores a `schedule_config` interval (e.g.
`{"minutes": 5}`) and exactly one of `input_params.command` or
`input_params.graph_type` with `graph_inputs`. Like harness items, jobs carry
**deployment configs** (`job_configs`) scoping them by device (`DEVICE_NAME`) and repo with
additive (include) / subtractive (exclude) rules — a job only runs on a device its configs
select.

A pure-asyncio scheduler runs inside the dashboard process (started in the app lifespan): it
polls for due jobs, executes commands in subprocesses or graphs in-process with a timeout,
and records every run in `job_executions` (status, timing, output/error, exit code). Executions left
`running` when the app stops are reconciled to `interrupted` on the next startup. Trigger an
immediate run with **Run Now** (or the `job_run_now` MCP tool), which ignores the schedule
and scoping.

Tune `JOB_POLL_INTERVAL`, `JOB_DEFAULT_TIMEOUT`, and `JOB_MAX_OUTPUT_BYTES` in your
environment's `.env.*` file.

## Meeting Context

The `meeting_ingest` graph imports meeting summaries, selected metadata and complete transcript
snapshots into PostgreSQL. It uses a configured provider factory; Granola is the first adapter.
After capture, a tool-calling agent generates reusable memories. The separate `persona` graph
reads saved transcripts and develops cumulative Profiles. Each workflow has its own job,
lease and retry state; failure in one does not block the other. Neither graph creates tickets.

Set source configuration and the real API key only in the gitignored `.env.production`:

```env
MEETING_SOURCES_JSON={"granola":{"provider":"granola","account_key":"personal","api_key_env":"GRANOLA_API_KEY","project":null,"provider_options":{}}}
GRANOLA_API_KEY=your-granola-api-key
```

Each key in `MEETING_SOURCES_JSON` is a connection label, not a meeting category.
Configure every account/provider connection there. The default graph inputs `{}` import
all configured connections; adding another connection does not require another job.

Leave `provider_options` empty to list everything accessible to the key. Granola also supports
`folder_id`, `space_id`, and `page_size` (1-30). Access follows the [Granola key scopes](https://docs.granola.ai/help-center/sharing/integrations/granola-api):
personal access covers notes the key owner can read; workspace keys cover public notes and
API-enabled spaces, and cannot read unshared private notes or folders. Summary imports exclude
private note text, attachments and arbitrary provider fields. Transcript snapshots are captured
separately using the same configured connection and its existing permissions.

Keep `account_key` stable when rotating credentials; use a new `account_key` for a different account.
Adding another provider requires an adapter and factory registration, then a configuration
change. Folder/project configuration changes reset the connection's incremental checkpoint
while retaining prior stored context. Provider/account switches retain their independent records.

Probe the real API, then verify the graph, persistence, and MCP reader in an owned disposable
database. These commands load only meeting settings/credentials from `.env.production` and
never use its database target. Native PostgreSQL/pgvector and `POSTGRES_BIN` follow the test
prerequisites below. Output contains counts and verification flags, without meeting content.

```sh
.venv/bin/python -m scripts.meetings probe --source granola
.venv/bin/python -m scripts.meetings verify-live --source granola --isolated-db --stage scan
.venv/bin/python -m scripts.meetings verify-live --source granola --isolated-db --stage context
.venv/bin/python -m scripts.meetings verify-live --source granola --isolated-db --stage transcript
```

After deploying the reviewed change, apply its migration through the existing confirmation
flow and restart the dashboard with the updated code:

Stop meeting runners on other devices before upgrading, and update every runner before
resuming the shared jobs. Migration `f8a0b1c2d3e4` adds independent persona leases, editable
profile context, directed relationships and meeting vocabulary. Migration `9d2f6a8c1b40`
adds field-level metadata provenance and protects existing human metadata. Migration
`c7a8e9f0b1d2` adds meeting labels, protected assessment sections, resumable assessment work
and profile history. Existing notes remain human-controlled; saved evidence becomes eligible
for assessment by the persona job. These migrations preserve completed persona receipts;
existing relationship links are backfilled without model calls.

```sh
./db.sh production --confirm-database <production-database-name>
```

Create **two jobs** through **Jobs → New Job**, selecting **Graph** as the job type:

| Name | Graph preset | Graph inputs | Run every | Timeout | Run on |
| --- | --- | --- | --- | --- | --- |
| Meetings | `meeting_ingest` | `{}` | 15 minutes | 600 seconds | All devices |
| Personas | `persona` | `{}` | 15 minutes | 600 seconds | All devices |

Existing installations with a meeting job must add the persona job separately; jobs are
not created automatically. Both graph presets default to a 600-second timeout and all devices.
Each running Agent Smith instance imports its configured connections into the shared database. Stable provider/account
identities, per-account claims and upserts prevent duplicate records when devices overlap.
Existing deployment configs remain visible in job details. Use **Run Now** for an immediate
import and **Executions** to inspect execution status. The dashboard must stay running
for periodic imports. Startup does not create meeting jobs or upgrade production schemas.
Source progress is also available through `meeting_sync_status` on `/mcp/meetings/`.

Open **Meetings** in the sidebar (`/meetings`) to browse and search saved summaries from all
connections. Select a meeting to read its summary, transcript, connection/provider details,
timestamps, revision and source link. Meeting context is shared across devices and is separate
from the generated memories shown on the Memory page.

Transcript capture starts when a meeting is first stored after this feature is enabled. This
includes older meetings from a newly connected account that have not already been imported.
Previously stored meetings, summary edits and repeated imports do not start another capture;
there is no automatic historical backfill. Unfinished captures retain their progress for a
later scheduled run. Keep the same all-connections, all-devices job and existing API key.

Meeting details show transcript capture status and safe failure information. A complete
snapshot is shown only after every provider page has been captured and validated. Pending,
unavailable, unsupported and failed captures remain distinct from an empty transcript; a
summary is never presented as a transcript. Anonymous or uncertain speakers stay unidentified.

Newly imported meetings also produce memories through a tool-calling agent after their complete
transcript is ready. The agent searches existing memories, reads every transcript window and
stages evidence-backed results before publication. Meeting details show the generated content,
exact evidence quotes, processing status and retry action; the same records are available on
**Memory**. Previously imported meetings can be queued explicitly with **Process meeting**
on their detail page. Pending work resumes without
regenerating completed windows or republishing acknowledged memories.

The memory agent prioritizes important information, material decisions, risks, blockers and
explicit action items. A commitment includes the task, owner, due phrase and dependencies
when supported by the transcript; missing owners or deadlines are never invented.

Meetings have their own purpose and subject labels, such as `product`, `security`, `paralign`,
`roadmapping`, `growth` and `operations`. New memory extraction proposes these labels in its
existing agent call. On a saved meeting, edit labels directly or use **Suggest labels** to
classify its saved title and summary, review the suggestion, and save it. This does not fetch
or replay a transcript. Human labels, including an explicit clear, take precedence.
Memories inherit these labels as separate meeting context, so older memories become easier
to find without rewriting their content, publication receipts or embeddings. Own memory tags
remain independently editable. Tag filters match both sets. Semantic searches retain their
existing bounded candidate set; a tag filter does not perform an exhaustive vector-store scan.

The independent persona job reads complete saved transcripts directly from PostgreSQL; it
does not need a Granola connection or successful memory generation. Previously published
memories provide optional context. Open **Profiles** in the sidebar to browse people across
meetings. Its main sections are **Overview**, **Drivers and motivations**, **Strengths**,
**Development areas**, **Working style**, and **Relationships**. An agent synthesizes these
assessments from saved, current observations, rather than presenting observations as the
assessment itself. Supporting evidence remains available in a collapsed section, with
confidence, attribution and exact transcript quotations. Meeting profile cards link to the
same records. Profile retries preserve completed memories.
On **Profiles**, **Run personas** invokes the configured persona job through the same path
as **Run Now** in Jobs. The processing card links its execution and identifies missing or
device-scoped job setup. A run uses saved, unreviewed transcripts and preserves checkpoints;
memory indexing is not a prerequisite. The same job updates assessments when their saved
evidence changes. A profile's build action uses its existing saved evidence without reading
transcripts again. Transcript capture still belongs to the Meetings job.

Profiles accumulate evidence as new meetings are digested. The profile list shows the number
of available source meetings and when each profile was last updated. The list and detail pages
refresh automatically; background updates preserve an open correction draft. Deleted profiles
stay hidden, and claims from unavailable meetings do not contribute to the visible counts.

Search profiles by name or linked email, filter by tags or stars, and choose a name or date
sort. Use **New profile** to add a person directly, with a name and optional email. Name-only
profiles are manual identities; link an email or assign the profile to a meeting speaker to
connect later evidence. **Edit profile** changes the name, tags and star without changing the
person's identity or saved evidence. Tags and stars survive later meeting updates. The detail page
lets you merge two profiles into one person. Both identities remain linked to the surviving
profile, including in future meetings and historical meeting links. You can also link another
email explicitly. Merging preserves evidence and human corrections; conflicting histories
cause the merge to fail instead of silently choosing one.

Optional human context includes nicknames, company, job role, start date, supervisor and other
metadata, plus editable assessment sections. Nicknames are searchable
labels, not proof of identity. Human notes and claim corrections remain authoritative during
later analysis. Directed relationships have their own editable labels and notes: A → B and
B → A are distinct. Neither gender nor marital status is inferred from names or voice.
The persona agent fills missing metadata from explicit statements with transcript evidence.
Existing values stay intact; conflicting information can be recorded as claims for review.
Editing or clearing a field protects that field from automatic fills. Generated metadata is
hidden if its source transcript becomes unavailable or its attribution changes.

Agent changes apply automatically. **History** records changes to assessments, metadata and
evidence, with before/after comparisons; it is not an approval queue. Existing profiles can
build their initial assessment from already saved observations. Unchanged evidence is skipped
before a model call, and cosmetic tag/star edits do not trigger synthesis. Subjective sections
need multiple supporting claims; otherwise the section reports insufficient evidence.
Editing or clearing a section makes it human-controlled until you explicitly allow automatic
updates again. Generated sections and history respect withdrawn or corrected source evidence.
Historical generated text may also be hidden when its original participant attribution version
changes; the raw audit is retained, and the UI explains that restriction. Unaffected current
assessments and evidence survive roster-only edits without additional model calls.

The agent can discover canonical profile names through a bounded directory and paginated
lookup, then read a selected profile's current details. A directory match never attributes an
anonymous speaker or silently merges people. When merging manually, the profile selected as
the target survives; the source identity redirects to it in future meetings.

Automatic matching across meetings uses a reliable email identity: an explicit speaker
email or an unambiguous match between a named speaker and the meeting's named attendee roster.
Names without an email and anonymous speaker labels remain meeting-scoped unless you explicitly
assign them to an existing profile. A shared microphone
without a distinguishable speaker does not create a person; silent attendees are not profiled.
No names or email aliases are guessed.

In a meeting's **Participants** card, add a name and email or choose an existing profile.
Once a transcript is available, select its speaker to explicitly attribute that speaker's
words. Participant additions are stored separately from provider metadata and survive syncs.
Changed speaker assignments retire the affected earlier profile claims
from the current view while retaining their evidence and correction history. Participant
changes wait until an active run finishes. Transcript pages retain the raw speaker and show
the effective confirmed identity, linking only to existing canonical profiles. Assignments
can update unfinished persona work; completed reviews and memories remain complete.

**Process meeting** explicitly enrolls an older saved meeting or retries its missing stages.
With compatible jobs running, explicit requests resume on the scheduler's next five-second
poll, including across bounded runs, rather than waiting for each 15-minute interval. Retry
backoff still applies. The processing card shows transcript sections analyzed, staged candidates,
saved outputs and next eligible attempt. Publication starts after all memory windows finish;
saved candidates are not yet published memories. This action does not create a job or restore
a deliberately deleted transcript. Previously imported meetings are not enrolled automatically in bulk.
Repeated processing, profile/nickname edits and vocabulary changes do not reopen completed
reviews or regenerate completed frozen memories.

On **Meetings**, open **Meeting vocabulary** to define terms and abbreviations. New memory analysis selects a
bounded matching glossary and saves it before its first model call. Retries reuse that glossary;
editing vocabulary does not alter transcripts or replay earlier meetings.

Use **Correct** or **Reject** on a profile claim to retain a human override with a reason.
Later analysis reads those overrides. Revision checks prevent a background analysis from
overwriting a concurrent edit; it rebuilds only its unfinished profile candidate. **Delete
profile** removes its claims and leaves an identity tombstone so later meetings cannot recreate
it automatically. Source-unavailable claims are hidden in the reader; human overrides remain
constraints for later analysis. Generated meeting-memory cards preserve the original output;
edits/deletions on Memory manage the published record separately.

The model roles `meeting_memory` and `persona` use the existing factory, defaulting to
`KIMI_K3` with curator settings as fallback. Configure them independently with
`MEETING_MEMORY_MODEL_*` and `PERSONA_MODEL_*`. `PERSONA_CONTEXT_PROVIDER=meetings` selects
the saved-meeting context adapter; Slack context is not implemented. Persona's optional
`source` input filters transcript extraction by stored connection name, not live API credentials.
Assessment refreshes use the profile's saved evidence across connections. Use `profile_id`
to target one saved profile without transcript extraction. Choose either `profile_id` or `source`.

Each graph handles one pending context within a 540-second work budget. Agent stages retain
their 150-second budget and model calls their 45-second bound. Memory/persona jobs require
600 seconds for execution and cleanup; legacy shorter timeouts receive that minimum at runtime.
Successful checkpoints resume promptly for explicit requests. Zero-progress timeouts and
dependency failures use bounded retries/backoff and expose safe, distinct error categories.

To import immediately, use the graphs MCP tool:

```python
run_graph(type="meeting_ingest", inputs={})
run_graph(type="persona", inputs={})
# Synthesize one existing profile from its saved evidence only:
run_graph(type="persona", inputs={"profile_id": "<profile UUID>"})
```

The optional `source` input restricts an explicitly targeted run to one connection, for
example `{"source":"granola"}`. Omit it for all connections. Each all-connection run snapshots
the connection configuration and shares its bounded work budget fairly. It attempts the
remaining connections after a source failure, then reports a failed execution with safe
per-source diagnostics. Partial progress counts that cannot be determined are reported as
unknown, with known completed counts kept separately. Interrupted or deferred work resumes
on later scheduled runs; connections with no or older attempts get priority.
For an import/transcript-only run, pass `{"digest":false}`. The isolated `verify-live`
commands use this mode and do not call a model or publish memories.

The meetings MCP server provides `meeting_list`, `meeting_get`, `meeting_search`, and
`meeting_sync_status`. List/search filter by source, project, and timezone-aware meeting
dates; reads see committed imports immediately. Each summary has a stable UUID, source URL,
provider/account identity, local revision, source timestamps, and selected meeting metadata.

Each connection pulls notes updated since its last completed pull using Granola's
[`updated_after` filter](https://docs.granola.ai/api-reference/list-notes). The saved boundary
is the start of that pull, with a one-minute overlap; it advances only after all pages
complete. Continued pages and retries keep the same frozen boundary. Unchanged references
in the overlap do not fetch summaries, transcripts, or rerun completed agent work.

There is no automatic daily history sweep. New connections and connections upgraded without
a safe checkpoint need one metadata baseline; already stored, unchanged notes are skipped.
Only newly imported meetings are automatically enrolled for analysis. Completed memory and
profile stages stay completed; unfinished stages resume, and older meetings can still be
processed explicitly from their detail page.

Graph imports stop after a 60-second work budget and resume the saved page/item checkpoint next time.
A database claim prevents overlapping source imports; outcomes include `continued`,
`completed`, `completed_with_warnings`, and `skipped_busy`. Failed/interrupted runs preserve
committed progress; a scan unfinished after 24 hours reports degraded status.

Context is eventually consistent: changed notes appear after the provider makes them
available with a newer `updated_at`. Access/readiness changes without a timestamp update
cannot be detected by incremental polling. Three unresolved detail observations hide a previously stored summary; explicit
deletion tombstones hide it immediately. A successful later fetch restores availability.
Listing absence alone does not delete context. Existing content remains stored for diagnosis;
there is no automatic retention purge, full revision history, or replication of source ACLs.
When a source meeting becomes unavailable or is deleted, its transcript is hidden and
unfinished capture stops. Stored transcript data is retained rather than automatically purged.

## Chat Rooms

The **Chat** page provides a shared transcript for the User and already-open Claude,
Codex, or Gemini coding sessions. Create a room, copy that agent's invite prompt into
its existing session, and use the dashboard composer as the User. Agents participate
through the `chat_read` and `chat_post` MCP tools, preserving the repository context
and tools they already have.

**Stop Agent Access** closes the room immediately to new messages and tells polling
agents to stop. Closing is irreversible; the transcript remains readable. It cannot
cancel an inference an agent had already started before the room was closed.

**AI participants** are additional LLM seats listed in `CHAT_MODEL_NAMES`. Each one
picks its own model with `CHAT_<NAME>_MODEL_PRESET` (e.g. `CHAT_KIMI_MODEL_PRESET=KIMI_K3`),
so participants can use different models and Bedrock endpoints; see the graph model
settings in `.env.default`. Mention one by
name in a User message — `@Kimi`, case-insensitive — and it posts one reply into the
room via the `chat` graph. Only User messages trigger mentions, so agents and AI
participants can never summon each other into a loop; agents can still summon one
deliberately with `run_graph("chat", {"room_id": N, "participant": "Kimi"})`. Each
participant name is also its stored message author, so pick names that don't collide
with `user`/`claude`/`codex`/`gemini` (enforced at startup). The graphs MCP server
must be restarted to refresh the `run_graph` tool description after changing graphs.

## Tests

```sh
./audit.sh
```

Runs backend tests (pytest) and frontend tests (Vitest). Pytest flags are forwarded:
`./audit.sh -x` stops on first failure, `./audit.sh -k test_plans` filters by name.
Default pytest tests and audits deny paid model inference, remove inherited paid credentials
and tracing, and propagate that mode to child processes. Scripted models/fake agents verify
the tool loops. Live-evaluation flags cannot override automated mode; these checks do not
claim a general network sandbox.

Install native PostgreSQL 17 and pgvector for tests. Set `POSTGRES_BIN` to the server
bin directory if it is not on PATH (Homebrew example: `$(brew --prefix postgresql@17)/bin`).
`./audit.sh` initializes a fresh cluster on a random loopback port, runs backend
tests with a temporary local memory store, and stops/removes only that owned cluster.
It never resets, drops, or connects to your configured application databases. CI uses
this same native backend audit command; no container runtime is required.

For direct `pytest tests/` invocations, set `APP_ENV=test` and `DATABASE_URL_TEST`
to a dedicated loopback database ending in `_test`. Remote targets and targets
matching configured production are rejected before connecting. Prefer `./audit.sh`
for automatic isolation.

## Evals

LLM-as-judge evaluation using DeepEval's G-Eval metric. Suites are defined in Postgres
and picked up automatically at test time.

```sh
./evals.sh                        # run all enabled suites
./evals.sh --suite rules_plans    # run a specific suite
```

Runs directly against the selected application database; the dashboard need not be
running. Defaults to production for compatibility; use `./evals.sh --env development`
to evaluate development suites. Evals intentionally record results in that database.
This is an explicit live, potentially billable workflow, separate from automated tests;
`./evals.sh` enables live-evaluation collection and refuses to run in automated mode.
Configure via `EVAL_MODEL`, `EVAL_JUDGE_MODEL`, and `EVAL_THRESHOLD` in the selected
environment's `.env.*` file.

## Database

Postgres stores harness items, eval configs, eval results, plans, meeting context, and—when
`MEMORY_BACKEND=pgvector`—memory content, metadata, and embeddings.
Schema is managed by Alembic. Development/test migrations run on startup. Production
startup only reads the migration revision and refuses incompatible schemas. Production
database creation and direct production Alembic commands (including downgrade) are
blocked. Forward upgrades require explicit database-name confirmation after review:

```sh
./db.sh development
./db.sh production --confirm-database <production-database-name>
```

Set `DATABASE_URL_DEVELOPMENT`, `DATABASE_URL_TEST`, or `DATABASE_URL_PRODUCTION`
in the corresponding `.env.*` file. Existing external production databases and data
remain in place. Install pgvector before initializing new local databases. Development
and test cannot select the configured production target.

For a new development database on an already running native PostgreSQL server, use
`APP_ENV=development .venv/bin/python -m services.db.create`, then `./run.sh dev`.
PostgreSQL is optional on the application host when the selected application database
already runs elsewhere; its native server binaries are required for isolated audits.

Application guards do not restrict arbitrary SQL clients. Use a production runtime
role that does not own schemas/tables and lacks database/schema creation permissions;
use separate credentials for reviewed migrations. This change does not alter existing
roles, grants, schemas, or production data.

## Environment

`.env.default` contains committed defaults. Each environment has its own override file
(`.env.development`, `.env.test`, `.env.production`) — all gitignored. Defaults are
overridden by the selected environment file, then explicit process variables.
`APP_ENV` defaults to development for Python entry points; `./run.sh` explicitly
selects production for compatibility. Local memory paths default to separate
`memory_store/<environment>` directories; shared production paths/indexes are rejected
in development and test.

See `.env.default` for all available configuration options.

## Existing installations

The code migration does not stop existing services or remove Docker volumes. Keep
those volumes and verified backups until native production has been checked. Existing
external PostgreSQL and Pinecone data stay in place; retain their URLs/backend settings.
For LanceDB, copy the existing `memory_store` volume while the old writer is stopped,
verify the copy, and set an absolute `MEMORY_STORE_PATH` in `.env.production`. Production
refuses an absent/empty store rather than silently starting with no memories. An entirely
new installation can use pgvector or a separately initialized LanceDB store.

Replace certificate paths such as `/certs/rds-global-bundle.pem` in database URLs with
the existing host certificate path. Keep TLS verification enabled. Recheck stored job
commands for Linux-specific tools and `/app` paths: native jobs run as the launching
user. Agent config files are accessed directly in that user's home directory. Only one
application process per environment is launched; do not add Uvicorn workers, because
the scheduler runs inside each application process. For persistence across reboots,
manage the production launcher through launchd/systemd under an appropriate user.

Existing development harness tools may contain MCP URLs for the old port 7654. Update
those development URLs before syncing to agents, or explicitly retain that port in
`.env.development` while production is stopped. The default production port stays 7654.

Native setup requires OS-specific prerequisites; the launcher does not install global
system packages or automatically change production infrastructure. Linux PostgreSQL
packages are documented by [PostgreSQL](https://www.postgresql.org/download/linux/ubuntu/),
and extension installation by [pgvector](https://github.com/pgvector/pgvector#installation).

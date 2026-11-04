# Claude memory Stop hook

The hook stays an agent hook. Its only task is bounded memory capture; capture
failure must allow the main session to stop. The replacement metadata is
[claude_memories.metadata.json](examples/claude_memories.metadata.json), which is
the authoritative prompt and permission artifact.

Draft each memory within 250 whitespace-separated words, retaining its supported scope and
identifiers. Rewrite oversized drafts and do not pad shorter ones. The shared memory write
boundary keeps the first 250 words before embedding and storage; capture evidence, source
pages and receipts keep their existing contracts. The artifact updates guidance for future
harness deployment and does not edit a live hook or skill.

## Deployment through the harness

1. Merge this change and retain the previous harness metadata for rollback.
2. **Before any Sync, update the `claude_memories` harness hook through the UI**
   using the reviewed metadata artifact; preserve its existing assignments.
3. Confirm `model: haiku` is inside `hooks[0]`, with `type: agent` and timeout 120;
   remove the legacy outer `metadata.model` key.
4. Review the three exact memory grants and the fixed Python/helper Bash prefix,
   then let Kevin run Sync through the harness UI.
5. Verify the generated hook and grants, reconnect the client if necessary, and
   run the first real publication check below.

Older hook metadata may have an outer model key. The compiler rejects that shape
with an instruction to move the model inside each hook entry; check the current
metadata before syncing. This change does not edit the live item or generated
client settings, run Sync, or restart clients.

`REPO_ROOT` expands through the existing host-path mechanism; interpreter and
helper paths remain quoted when the checkout contains spaces. Dynamic session,
transcript, receipt, and UUID arguments must be shell-quoted individually. The
permission authorizes only the fixed helper prefix, rather than arbitrary Python
or Bash. These grants apply to Claude sessions using the generated settings,
not exclusively the hook, so review them as capabilities of that client.

## Capture and recovery contract

The helper reads canonical parent, child-agent, and verified workflow result
records from the session's transcript tree. It bounds records and output,
redacts complete text blocks before pagination, and returns at most 12 KiB of
JSON containing untrusted evidence and verified Git scopes. A non-Git working
directory supplies no invented project name; different repositories retain
separate scopes. Fragment scope IDs are primary; an explicit, unambiguous
current-page filesystem mapping can support a fragment without IDs. Ambiguous
candidate scope is deliberately excluded and reported as `skipped_scope`, so an
otherwise assessed page can advance; actual helper scope failures retain it.
Uncertain personal data, secrets, PHI, instructions, and claims
must still be excluded by the agent because redaction is incomplete.

Each page is a **SNAPSHOT** receipt. The state machine is `ready` → an acknowledged
`saved`, `duplicate`, or `nothing_to_save`; lookup/save failures retain the
pending page, and helper scope errors leave coverage unacknowledged. `waiting`
means an incomplete trailing record; `caught_up` means
the inspected sources currently have no additional complete records. Every read
can return `busy` or a safe error. There is no background worker or automatic
retry loop: later Stops resume pending coverage. The agent uses at most two
pages, three additions, six searches, and one recent-memory listing per Stop;
the hook timeout is 120 seconds. Budget exhaustion leaves work pending.

Acknowledgement checks file identity, scanned bytes, cursor coverage, and the
scope/context hash. Source or scope drift rejects the acknowledgement; appended
records remain for later capture. Partial publication can leave saved memories
and a pending page, so retries perform semantic deduplication; this is not
exactly-once delivery. Only confirmed returned UUIDs count as saved. Current
`last_assistant_message` evidence can precede its transcript record; it never
advances an unrelated receipt, and its later record is deduplicated normally.
The `record-current` command records only confirmed current-only memory UUIDs
with evidence kind `hook_last_assistant_message`, independently of disk cursors.
`caught_up` and `waiting` stop disk pagination but still allow this separate
assessment using the returned verified-scope snapshot; `busy` or helper errors
stop the capture attempt.

State under `.runtime/claude-memory-capture/` stores identifiers, offsets,
hashes, receipts, safe diagnostics, and confirmed memory IDs, not transcript or
memory prose. Inspect a session without printing its evidence:

```sh
.venv/bin/python scripts/claude_memory_context.py status --session-id SESSION_UUID
```

`last_run`, `last_ack`, `pending`, and `processed_sources` distinguish a handled
failure from acknowledged coverage. The prompt requires `ok:true`; timeout and
runtime-error handling in Claude 2.1.312 is also nonblocking, but an unexpected
valid `ok:false` model verdict can still block Stop.

## Verification and publication gate

Run the focused parser, capture, CLI, permission, Sync, and artifact tests before
deployment:

```sh
./audit.sh --backend-only -q -k 'claude_memory or claude_transcript or hook_permissions or hook_settings or hook_sync'
```

Paid checks use the exact VS Code 2.1.312 binary, Haiku, a scratch project,
`--setting-sources project`, `--strict-mcp-config`, and synthetic transcripts.
The capability probe exposes only read-only lookup tools. Capture checks add a
clearly named `capture_candidate` scratch-catalog sink and mechanically replace
only the helper prefix and tool name in the reviewed prompt; the real CLI and
`CaptureStore` use injected synthetic roots. `memory_add` remains absent and
explicitly denied. No check processes historical conversations with a model.

| Check | Observed result |
| --- | --- |
| First isolated launch in the sandbox | `Not logged in · Please run /login`; $0; no hook/tool execution |
| Same isolated fixture with normal authentication outside the sandbox | Plain and quoted-space helper prefixes executed; read-only MCP echoed the helper nonce |
| Unfinished main task in that successful check | Stopped in one main-agent turn; 28.836 s; `claude-haiku-5-5`; $0.00352548 |
| Reviewed capture procedure with a 351,447-byte hostile synthetic fixture | One scratch candidate UUID acknowledged by the real store; no hostile/secret canary saved; one main-agent turn; 30.023 s; $0.004511885 |
| Same procedure with lookups explicitly denied | Lookup failure recorded; pending receipt retained; no source advanced or candidate saved; one main-agent turn; 32.796 s; $0.00474612 |
| Same procedure with a helper-rejected synthetic source | Safe `source_outside_transcripts_root` error; no lookup, candidate, acknowledgement, or source advance; one main-agent turn; 8.969 s; $0.00102235 |

Five client launches consumed the full experiment budget: one sandbox
authentication failure and four successful live checks, totaling $0.013805835.

The capability check proves actual helper/MCP execution, not merely a successful
Stop. It does **not** prove real memory publication. After Kevin updates the
harness item and runs Sync, use one ordinary, nonsensitive technical session:
confirm the hook's project scope, a returned real memory UUID, the corresponding
`last_ack`, and no duplicate on a subsequent Stop. Verify a real lookup against
the connected server separately. Do not replay historical sessions or fabricate
a production memory for an experiment. Cost and latency vary with pages, model
turns, and tools; the measurements above are examples, not per-Stop guarantees.

## Permission ownership and rollback

Sync preserves unrelated permission keys and preexisting grants. A sidecar named
`.settings.json.agent-smith-hooks.json` beside Claude's generated settings tracks
only grants introduced by hook Sync. Removing a managed grant retires it only
when no selected hook still requests it; an identical preexisting grant remains.
An interrupted transaction records intent and recovers when the current rule
fingerprint matches its before/after state; divergent concurrent edits stop Sync
for review. Keep this sidecar; deleting it loses ownership provenance.

For rollback, use the harness UI to restore the prior reviewed prompt with its
model still normalized inside the hook entry, and remove unwanted managed
permission declarations. Run Sync using this version first and verify that only
owned, retired grants disappeared; then revert the source change if required.
Do not restore the invalid outer-model layout or directly edit client files.

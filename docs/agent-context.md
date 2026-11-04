# Agent context and the DO NOT TRUNCATE skill

Selected context must reach its agent completely, or processing must stop with a clear limit error. Chat drains all transcript pages; Improve gathers every selected plan, review, memory and job before its existing complete map batches. Meeting labels receive the full saved summary, and profile workflows preserve authorized history, corrections and evidence.

Rubric graders retain complete visible messages, tool calls and full rule text through the pinned `deepagents==0.7.22` adapter. Evaluation scoring receives the complete judge prompt and rule, even when numbered evaluation steps or generated steps are used. Transport metadata, private tool artifacts, deleted profiles and unavailable source text remain subject to existing visibility rules.

Pagination and processing windows preserve complete records and explicit continuation. Oversized individual inputs and complete profile/speaker envelopes fail explicitly rather than returning shortened success. Retired speaker inference stays inactive.

## Save the skill in the UI

1. Open **Skills**, then create a skill named `do_not_truncate` or edit your existing equivalent.
2. Paste the following text into its Markdown body.
3. Select the intended agents and deployment scopes, enable it, and save.
4. Use **Sync** when ready to distribute it, then reconnect or restart affected agent clients.

A saved harness skill guides assigned coding agents; it does not automatically become an internal graph's system prompt. The application changes enforce context fidelity at the owned graph and grader boundaries.

## Copyable skill

```markdown
# DO NOT TRUNCATE AGENT CONTEXT

Pass complete selected instructions, sources, history, tool results, and evidence to every agent, evaluator, and grader.

Never shorten selected context using prefix/tail slices, excerpts, silent record limits, character budgets, or token budgets.

Never substitute summaries or compact projections unless the user explicitly authorizes that transformation.

Paginate or process in ordered batches only when every selected item is covered and continuation is explicit.

Preserve source identity, ordering, provenance, corrections, and privacy boundaries across retries, tools, frameworks, and inter-agent messages.

If complete context exceeds a real limit, fail before inference and identify the limit and source; request a scope decision.

Inspect framework middleware and dependencies for hidden clipping, including grader inputs and retry context.

Verify actual model requests retain beginning, middle, and ending content plus every selected record.

Keep output-truncation guards; reject incomplete responses instead of treating them as successful results.

Authorized exception: memory records must fit the configured embedding window, capped at 256 total tokenizer tokens, including reserved tokens and source references.

Validate generated memories with the embedding tokenizer and require concise rewrites before saving oversized drafts; use identical final text for embedding and storage.

Apply this exception only to memory records; never generalize it to other agent context, source documents, history, or evidence.
```

The memory exception applies to the record being generated and saved, not its source documents, historical evidence, grader transcript or unrelated agent input. The embedding model/window remain unchanged; the configured MiniLM tokenizer reserves two of its 256 input tokens, leaving 254 tokens for text, including any source footer. Generation guidance and enforcement are supplied by the memory-limit change; saving this skill alone does not add that backend validation.


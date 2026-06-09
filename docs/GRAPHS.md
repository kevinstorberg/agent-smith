# Graph Runtime

Cairn provides a config-driven LangGraph runtime for common agent workflows and
keeps app-specific graph behavior in YAML, tools, prompts, and services.

## Runtime Config

Graph YAML files live under `config/graphs/{name}.yaml` and merge over
`config/default.yaml`:

```yaml
llm:
  provider: fake
  model: local-fake
tools:
  - lookup_record
runtime:
  kind: react
  prompt: system_instructions
  recursion_limit: 25
checkpoint:
  backend: memory
```

Use `llm.provider: fake` for deterministic local/manual validation without
cloud credentials. Use `openai` or `anthropic` for real model calls.

The built-in runtime kind is `react`. `runtime.prompt` loads
`config/prompts/{name}.txt`. `checkpoint.backend` supports `none`, `memory`, and
`postgres`; Postgres checkpointing requires the optional `graph-postgres`
dependency group.

The legacy `checkpointing: true` flag still maps to memory checkpointing.

## Builders

- `build_graph_from_config(name)` builds the real ReAct graph using configured
  LLM, tools, prompt, and checkpoint backend.
- `build_graph_runtime(name, scope={...})` returns the graph plus runtime
  metadata such as recursion limit.
- `build_config_summary_graph(name)` is the credential-free smoke graph for
  verifying config loading.

## Endpoints

The app includes graph endpoints by default:

```http
POST /graphs/{graph_name}/invoke
POST /graphs/{graph_name}/stream
```

Both accept:

```json
{
  "state": {"messages": []},
  "thread_id": "optional-thread",
  "context": {}
}
```

`thread_id` maps to LangGraph `configurable.thread_id`. `context` is copied into
`ToolContext.scope` so tools can receive request-scoped values without globals.
The stream endpoint returns Server-Sent Events.

## Layering

Tools and graph nodes should call application services or repositories for
domain work. Do not put business rules in graph endpoint handlers. Broken graph
configuration raises a standard API error envelope before execution starts;
streaming failures emit a final SSE error event when possible.

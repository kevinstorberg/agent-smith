import pytest
from langchain_core.messages import HumanMessage

from config.models import CheckpointConfig, GraphConfig, GraphRuntimeConfig, LLMConfig
from src.graphs.base import GraphFactory, GraphRuntime, build_config_summary_graph, build_graph_runtime
from src.graphs.checkpointing import create_checkpointer
from src.models.state import BaseState, add_messages_reducer


class TestBaseState:
    def test_base_state_has_messages(self):
        state = BaseState(messages=[])
        assert state["messages"] == []

    def test_add_messages_reducer_appends(self):
        existing = ["hello"]
        new = ["world"]
        result = add_messages_reducer(existing, new)
        assert result == ["hello", "world"]

    def test_add_messages_reducer_empty(self):
        result = add_messages_reducer([], ["first"])
        assert result == ["first"]


class TestGraphFactory:
    def test_graph_factory_protocol(self):
        assert hasattr(GraphFactory, "build")

    def test_config_summary_graph_remains_credential_free(self):
        graph = build_config_summary_graph("default")
        result = graph.invoke({"messages": []})

        assert result["graph_config"]["name"] == "default"
        assert result["graph_config"]["tools"] == []
        assert result["graph_config"]["runtime"]["kind"] == "react"
        assert result["graph_config"]["checkpoint"]["backend"] == "none"

    def test_config_summary_graph_unknown_graph_still_works(self):
        graph = build_config_summary_graph("nonexistent")
        result = graph.invoke({"messages": []})

        assert result["graph_config"]["name"] == "nonexistent"

    def test_build_graph_runtime_composes_config_tools_prompt_llm_and_checkpoint(self, monkeypatch):
        import src.graphs.base as graph_base

        calls = {}

        def fake_load_graph_config(graph_name: str, *, require_file: bool = False):
            calls["graph_name"] = graph_name
            calls["require_file"] = require_file
            return GraphConfig(
                name=graph_name,
                llm=LLMConfig(provider="openai", model="model-a", max_tokens=123),
                tools=["tool-a"],
                runtime=GraphRuntimeConfig(prompt="system", recursion_limit=7),
                checkpoint=CheckpointConfig(backend="memory"),
            )

        def fake_load_tools(tool_names, context):
            calls["tool_names"] = tool_names
            calls["tool_context"] = context
            return ["loaded-tool"]

        def fake_build_llm(**kwargs):
            calls["llm_kwargs"] = kwargs
            return "llm"

        def fake_create_checkpointer(config):
            calls["checkpointer_config"] = config
            return "checkpointer"

        def fake_create_react_agent_graph(llm, tools, **kwargs):
            calls["agent"] = {"llm": llm, "tools": tools, "kwargs": kwargs}
            return FakeCompiledGraph()

        monkeypatch.setattr(graph_base, "load_graph_config", fake_load_graph_config)
        monkeypatch.setattr(graph_base, "load_tools", fake_load_tools)
        monkeypatch.setattr(graph_base, "build_llm", fake_build_llm)
        monkeypatch.setattr(graph_base, "create_checkpointer", fake_create_checkpointer)
        monkeypatch.setattr(graph_base, "load_prompt", lambda name: f"prompt:{name}")
        monkeypatch.setattr(graph_base, "create_react_agent_graph", fake_create_react_agent_graph)

        runtime = build_graph_runtime("workflow-a", model_override="model-b", scope={"request_id": "request-1"})

        assert runtime.graph.invoked is False
        assert runtime.recursion_limit == 7
        assert calls["graph_name"] == "workflow-a"
        assert calls["require_file"] is True
        assert calls["tool_names"] == ["tool-a"]
        assert calls["tool_context"].graph_name == "workflow-a"
        assert calls["tool_context"].scope == {"request_id": "request-1"}
        assert calls["llm_kwargs"]["model"] == "model-b"
        assert calls["agent"] == {
            "llm": "llm",
            "tools": ["loaded-tool"],
            "kwargs": {
                "system_prompt": "prompt:system",
                "checkpointer": "checkpointer",
                "name": "workflow-a",
            },
        }

    def test_build_graph_runtime_rejects_unknown_runtime_kind(self, monkeypatch):
        import src.graphs.base as graph_base

        monkeypatch.setattr(
            graph_base,
            "load_graph_config",
            lambda graph_name, *, require_file=False: GraphConfig(
                name=graph_name, runtime=GraphRuntimeConfig(kind="custom")
            ),
        )

        with pytest.raises(ValueError, match="Unknown graph runtime kind"):
            build_graph_runtime("workflow-a")

    async def test_graph_runtime_awaits_awaitable_event_stream(self):
        runtime = GraphRuntime(
            graph=AwaitableStreamGraph(),
            config=GraphConfig(name="workflow-a"),
            recursion_limit=3,
        )

        events = [event async for event in runtime.astream_events({"messages": []}, thread_id="thread-a")]

        assert events == [{"type": "token", "content": "hello"}]
        assert runtime.graph.configs == [{"recursion_limit": 3, "configurable": {"thread_id": "thread-a"}}]

    async def test_build_graph_runtime_invokes_with_fake_llm_provider(self, monkeypatch):
        import src.graphs.base as graph_base

        monkeypatch.setattr(
            graph_base,
            "load_graph_config",
            lambda graph_name, *, require_file=False: GraphConfig(
                name=graph_name,
                llm=LLMConfig(provider="fake", model="local-fake", max_tokens=128),
                runtime=GraphRuntimeConfig(recursion_limit=3),
            ),
        )

        runtime = build_graph_runtime("workflow-a")
        result = await runtime.ainvoke({"messages": [HumanMessage(content="Summarize this project")]})

        assert "messages" in result
        assert '"provider": "fake"' in result["messages"][-1].content
        assert "Summarize this project" in result["messages"][-1].content


class TestCheckpointing:
    def test_no_checkpoint_backend_returns_none(self):
        config = GraphConfig(checkpoint=CheckpointConfig(backend="none"))

        assert create_checkpointer(config) is None

    def test_memory_checkpoint_backend_returns_langgraph_memory_saver(self):
        from langgraph.checkpoint.memory import InMemorySaver

        config = GraphConfig(checkpoint=CheckpointConfig(backend="memory"))

        assert isinstance(create_checkpointer(config), InMemorySaver)

    def test_memory_checkpoint_backend_reuses_saver(self):
        import src.graphs.checkpointing as checkpointing

        checkpointing.reset_checkpointers()
        config = GraphConfig(checkpoint=CheckpointConfig(backend="memory"))

        assert create_checkpointer(config) is create_checkpointer(config)

    def test_legacy_checkpointing_true_maps_to_memory_backend(self):
        config = GraphConfig(checkpointing=True)

        assert config.checkpoint.backend == "memory"

    def test_unknown_checkpoint_backend_raises(self):
        config = GraphConfig(checkpoint=CheckpointConfig(backend="unknown"))

        with pytest.raises(ValueError, match="Unknown graph checkpoint backend"):
            create_checkpointer(config)

    def test_postgres_checkpoint_backend_requires_optional_dependency(self, monkeypatch):
        import src.graphs.checkpointing as checkpointing

        checkpointing.reset_checkpointers()
        monkeypatch.setattr(
            checkpointing,
            "_load_postgres_dependencies",
            lambda: (_ for _ in ()).throw(RuntimeError("requires langgraph-checkpoint-postgres")),
        )

        config = GraphConfig(checkpoint=CheckpointConfig(backend="postgres"))

        with pytest.raises(RuntimeError, match="requires langgraph-checkpoint-postgres"):
            create_checkpointer(config, database_url="postgresql+asyncpg://user:pass@db/app")

    def test_postgres_checkpoint_backend_uses_sync_database_url(self, monkeypatch):
        import src.graphs.checkpointing as checkpointing

        checkpointing.reset_checkpointers()
        fake_psycopg = FakePsycopg()
        monkeypatch.setattr(checkpointing, "_load_postgres_dependencies", lambda: (FakePostgresSaver, fake_psycopg))

        config = GraphConfig(checkpoint=CheckpointConfig(backend="postgres"))
        saver = create_checkpointer(config, database_url="postgresql+asyncpg://user:pass@db/app")

        assert isinstance(saver, FakePostgresSaver)
        assert saver.setup_called is True
        assert fake_psycopg.connections == [("postgresql://user:pass@db/app", True)]

        assert create_checkpointer(config, database_url="postgresql+asyncpg://user:pass@db/app") is saver
        assert fake_psycopg.connections == [("postgresql://user:pass@db/app", True)]


class FakeCompiledGraph:
    def __init__(self) -> None:
        self.invoked = False
        self.configs = []

    async def ainvoke(self, state, *, config):
        self.invoked = True
        self.configs.append(config)
        return {"state": state}


class AwaitableStreamGraph:
    def __init__(self) -> None:
        self.configs = []

    def astream_events(self, state, *, config, version):
        self.configs.append(config)
        assert version == "v2"
        return self._stream()

    async def _stream(self):
        async def events():
            yield {"type": "token", "content": "hello"}

        return events()


class FakePostgresSaver:
    def __init__(self, connection):
        self.connection = connection
        self.setup_called = False

    def setup(self):
        self.setup_called = True


class FakePsycopg:
    def __init__(self) -> None:
        self.connections = []

    def connect(self, connection_string: str, *, autocommit: bool):
        self.connections.append((connection_string, autocommit))
        return "connection"

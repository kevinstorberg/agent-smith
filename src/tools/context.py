from pydantic import BaseModel, Field


class ToolContext(BaseModel):
    graph_name: str = ""
    tools: list[str] = Field(default_factory=list)
    enabled_sources: list[str] = Field(default_factory=list)
    source_limits: dict[str, int] = Field(default_factory=dict)
    scope: dict | None = None

    @classmethod
    def from_graph_config(cls, graph_config, *, scope: dict | None = None) -> "ToolContext":
        return cls(
            graph_name=getattr(graph_config, "name", ""),
            tools=getattr(graph_config, "tools", []),
            enabled_sources=[],
            source_limits={},
            scope=scope,
        )

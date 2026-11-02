from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata
from mcp.types import Tool
from pydantic import BaseModel


class _ContractMetadata(FuncMetadata):
    def pre_parse_json(self, data: dict[str, Any]) -> dict[str, Any]:
        # Validated strings such as "null" are literal data, not encoded arguments.
        return data


class ContractMCP(FastMCP):
    def __init__(self, name: str, contracts: Mapping[str, type[BaseModel]]) -> None:
        super().__init__(name)
        self._input_contracts = MappingProxyType(dict(contracts))

    def add_tool(self, fn: Callable[..., Any], name: str | None = None, *args: Any, **kwargs: Any) -> None:
        super().add_tool(fn, name, *args, **kwargs)
        registered = self._tool_manager.get_tool(name or fn.__name__)
        if registered is None:
            raise ToolError("Tool registration did not return a tool")
        metadata = registered.fn_metadata
        registered.fn_metadata = _ContractMetadata(**{
            key: getattr(metadata, key) for key in type(metadata).model_fields
        })

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        parameters = arguments if arguments is not None else {}
        contract = self._input_contracts.get(name)
        if contract is None:
            raise ToolError(f"No input contract is registered for {name}")
        # Validate before the SDK can coerce values or discard unknown fields.
        try:
            contract.model_validate(parameters)
        except ValueError as error:
            raise ToolError(str(error)) from None
        return await super().call_tool(name, parameters)

    async def list_tools(self) -> list[Tool]:
        registered = await super().list_tools()
        for tool in registered:
            contract = self._input_contracts.get(tool.name)
            if contract is None:
                raise ToolError(f"No input contract is registered for {tool.name}")
            tool.inputSchema = contract.model_json_schema()
        return registered

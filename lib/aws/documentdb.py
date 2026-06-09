import asyncio
from typing import Any, Protocol

from lib.aws.base import AWSClientProtocol


class DocumentDBAdmin(Protocol):
    def command(self, command: str) -> Any: ...


class DocumentDBDriverClient(Protocol):
    admin: DocumentDBAdmin

    def close(self) -> None: ...


class DocumentDBClient(AWSClientProtocol):
    def __init__(
        self,
        connection_string: str = "",
        *,
        client: DocumentDBDriverClient | None = None,
        server_selection_timeout_ms: int = 5000,
    ) -> None:
        if client is None and not connection_string:
            raise ValueError("DocumentDBClient requires connection_string or injected client")

        self._connection_string = connection_string
        self._client: DocumentDBDriverClient | None = client or self._create_client(
            connection_string, server_selection_timeout_ms
        )

    async def health_check(self) -> bool:
        if self._client is None:
            return False
        try:
            await asyncio.to_thread(self._client.admin.command, "ping")
        except Exception:
            return False
        return True

    async def close(self) -> None:
        if self._client is None:
            return

        client = self._client
        self._client = None
        await asyncio.to_thread(client.close)

    def _create_client(self, connection_string: str, server_selection_timeout_ms: int) -> DocumentDBDriverClient:
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise RuntimeError(
                "DocumentDBClient requires pymongo. Install with `poetry install --with documentdb`."
            ) from exc

        return MongoClient(connection_string, serverSelectionTimeoutMS=server_selection_timeout_ms)

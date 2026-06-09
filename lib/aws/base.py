from typing import Protocol, runtime_checkable


@runtime_checkable
class AWSClientProtocol(Protocol):
    async def health_check(self) -> bool: ...
    async def close(self) -> None: ...

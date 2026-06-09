from abc import ABC, abstractmethod


class BaseJob(ABC):
    """Base class for scheduled background jobs.

    Subclass and implement execute(). New jobs should accept a JobContext
    argument. Existing no-argument execute() methods remain supported by the
    runtime compatibility adapter.
    """

    name: str
    timeout_seconds: float | None = None

    @abstractmethod
    async def execute(self) -> None: ...

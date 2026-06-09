import importlib
from dataclasses import dataclass, field
from typing import Any

from src.jobs.base import BaseJob


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    backoff_seconds: float = 0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("RetryPolicy.max_attempts must be at least 1")
        if self.backoff_seconds < 0:
            raise ValueError("RetryPolicy.backoff_seconds must be non-negative")


@dataclass(frozen=True)
class LockPolicy:
    enabled: bool = True
    key: str | None = None
    ttl_seconds: float = 300

    def __post_init__(self) -> None:
        if self.ttl_seconds <= 0:
            raise ValueError("LockPolicy.ttl_seconds must be positive")


@dataclass(frozen=True)
class JobDefinition:
    name: str
    factory: str | None = None
    trigger: str = "interval"
    trigger_kwargs: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    lock_policy: LockPolicy = field(default_factory=LockPolicy)
    metadata: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("JobDefinition.name is required")
        if not self.trigger.strip():
            raise ValueError("JobDefinition.trigger is required")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("JobDefinition.timeout_seconds must be positive when set")
        if not isinstance(self.trigger_kwargs, dict):
            raise ValueError("JobDefinition.trigger_kwargs must be a dictionary")
        if not isinstance(self.metadata, dict):
            raise ValueError("JobDefinition.metadata must be a dictionary")

    @property
    def lock_key(self) -> str:
        return self.lock_policy.key or f"job:{self.name}"

    def validate_for_persistent_store(self) -> None:
        if not self.factory:
            raise ValueError(
                f"Job {self.name!r} must define an importable factory path when persistent scheduling is enabled"
            )
        load_job_factory(self.factory)

    def create_job(self) -> BaseJob:
        if not self.factory:
            raise ValueError(f"Job {self.name!r} does not define a factory path")
        factory = load_job_factory(self.factory)
        created = factory()
        if not isinstance(created, BaseJob):
            raise TypeError(f"Job factory {self.factory!r} must return a BaseJob instance")
        return created


def import_path_for(target: Any) -> str:
    module = getattr(target, "__module__", None)
    qualname = getattr(target, "__qualname__", None)
    if not module or not qualname or "<locals>" in qualname:
        raise ValueError("Job factories must be importable module-level callables or classes")
    return f"{module}:{qualname}"


def load_job_factory(path: str) -> Any:
    module_name, separator, attribute_path = path.partition(":")
    if not separator or not module_name or not attribute_path:
        raise ValueError(f"Job factory path must use 'module:attribute', got {path!r}")

    module = importlib.import_module(module_name)
    target: Any = module
    for attribute in attribute_path.split("."):
        target = getattr(target, attribute)

    if isinstance(target, type) and issubclass(target, BaseJob):
        return target
    if callable(target):
        return target
    raise TypeError(f"Job factory path {path!r} does not resolve to a callable")

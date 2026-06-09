import importlib
import pkgutil
from collections.abc import Callable
from typing import Any, TypeVar

from src.jobs.base import BaseJob
from src.jobs.definitions import JobDefinition, LockPolicy, RetryPolicy, import_path_for

JobFactoryT = TypeVar("JobFactoryT", bound=Callable[..., BaseJob] | type[BaseJob])

_REGISTERED_JOBS: dict[str, JobDefinition] = {}
_DISCOVERED_PACKAGES: set[str] = set()
_INTERNAL_MODULES = {
    "base",
    "context",
    "definitions",
    "locks",
    "registry",
    "router",
    "runner",
    "scheduler",
    "stores",
    "runtime",
}


def register_job(
    *,
    name: str | None = None,
    trigger: str = "interval",
    trigger_kwargs: dict[str, Any] | None = None,
    timeout_seconds: float | None = None,
    retry_policy: RetryPolicy | None = None,
    lock_policy: LockPolicy | None = None,
    enabled: bool = True,
) -> Callable[[JobFactoryT], JobFactoryT]:
    def decorator(factory: JobFactoryT) -> JobFactoryT:
        job_name = name or getattr(factory, "name", None) or getattr(factory, "__name__", None)
        if not job_name:
            raise ValueError("Registered jobs must have a name")
        definition = JobDefinition(
            name=str(job_name),
            factory=import_path_for(factory),
            trigger=trigger,
            trigger_kwargs=dict(trigger_kwargs or {}),
            timeout_seconds=timeout_seconds,
            retry_policy=retry_policy or RetryPolicy(),
            lock_policy=lock_policy or LockPolicy(),
            enabled=enabled,
        )
        _REGISTERED_JOBS[definition.name] = definition
        return factory

    return decorator


def registered_jobs() -> dict[str, JobDefinition]:
    return dict(_REGISTERED_JOBS)


def clear_registered_jobs() -> None:
    _REGISTERED_JOBS.clear()
    _DISCOVERED_PACKAGES.clear()


def discover_jobs(package_name: str = "src.jobs") -> dict[str, JobDefinition]:
    if package_name in _DISCOVERED_PACKAGES:
        return registered_jobs()

    package = importlib.import_module(package_name)
    package_paths = getattr(package, "__path__", None)
    if package_paths is None:
        raise ValueError(f"Job discovery package {package_name!r} is not a package")

    for _, module_name, _ in pkgutil.iter_modules(package_paths):
        if module_name.startswith("_") or module_name in _INTERNAL_MODULES:
            continue
        importlib.import_module(f"{package_name}.{module_name}")

    _DISCOVERED_PACKAGES.add(package_name)
    return registered_jobs()

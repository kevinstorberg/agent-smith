from typing import Any, Protocol, runtime_checkable

SERVICE_REGISTRY: dict[str, type] = {}


def register_service(name: str):
    def decorator(cls):
        SERVICE_REGISTRY[name] = cls
        return cls

    return decorator


@runtime_checkable
class ServiceProtocol(Protocol):
    async def health_check(self) -> bool: ...
    async def close(self) -> None: ...

    @classmethod
    def from_settings(cls, settings: Any) -> "ServiceProtocol": ...


def create_service(name: str, **kwargs) -> ServiceProtocol:
    if name not in SERVICE_REGISTRY:
        available = ", ".join(sorted(SERVICE_REGISTRY.keys()))
        raise ValueError(f"Unknown service '{name}'. Available: {available}")
    cls = SERVICE_REGISTRY[name]
    if kwargs:
        return cls(**kwargs)
    return cls.from_settings(None)

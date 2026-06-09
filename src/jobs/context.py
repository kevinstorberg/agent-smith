from dataclasses import dataclass, field
from typing import Any

from cache.base import CacheBackend
from config.models import DefaultConfig
from db.unit_of_work import UnitOfWorkFactory
from src.settings import Settings


@dataclass(frozen=True)
class JobContext:
    config: DefaultConfig
    settings: Settings
    unit_of_work_factory: UnitOfWorkFactory
    cache_backend: CacheBackend | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

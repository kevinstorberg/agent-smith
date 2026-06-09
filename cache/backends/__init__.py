from cache.base import CacheBackend
from config.loader import load_default_config
from config.models import CacheConfig
from lib.cairn.singleton import singleton


def create_cache_backend(config: CacheConfig) -> CacheBackend:
    """Create a cache backend from explicit cache config."""
    backend_name = config.backend.lower()

    if backend_name == "memory":
        from cache.backends.memory import InMemoryCacheBackend

        return InMemoryCacheBackend()
    elif backend_name == "redis":
        from cache.backends.redis import RedisCacheBackend

        return RedisCacheBackend()

    raise ValueError(f"Unknown cache backend: {backend_name}. " f"Valid options: memory, redis")


@singleton
def get_cache_backend() -> CacheBackend:
    """Get cache backend instance based on configuration."""
    config = load_default_config()
    return create_cache_backend(config.cache)


reset_cache_backend = get_cache_backend.reset

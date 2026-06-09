"""Singleton pattern implementation for Cairn template.

This module provides a decorator for implementing the singleton pattern consistently
across all backend factories and service instances.
"""

import functools
from typing import Callable, TypeVar

T = TypeVar("T")


def singleton(func: Callable[[], T]) -> Callable[[], T]:
    """Decorator that ensures a function returns the same instance every time.

    This decorator caches the first return value and returns it on subsequent calls.
    It also adds a `reset()` method to the function for testing purposes.

    Usage:
        >>> @singleton
        ... def get_backend():
        ...     return Backend()
        ...
        >>> backend1 = get_backend()  # Creates instance
        >>> backend2 = get_backend()  # Returns same instance
        >>> assert backend1 is backend2
        ...
        >>> # For testing
        >>> get_backend.reset()  # Force recreation on next call
        >>> backend3 = get_backend()  # Creates new instance
        >>> assert backend3 is not backend1

    Returns:
        Decorated function that implements singleton pattern with reset capability
    """
    instance: T | None = None

    @functools.wraps(func)
    def wrapper() -> T:
        nonlocal instance
        if instance is None:
            instance = func()
        return instance

    def reset() -> None:
        """Reset singleton - next call will create new instance.

        This is primarily useful for testing when you need to force recreation
        of the singleton instance.
        """
        nonlocal instance
        instance = None

    wrapper.reset = reset  # type: ignore[attr-defined]
    return wrapper

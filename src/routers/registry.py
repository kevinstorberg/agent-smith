import importlib
import logging
import pkgutil

from fastapi import APIRouter, FastAPI

from lib.cairn.paths import get_module_dir

logger = logging.getLogger(__name__)

ROUTER_REGISTRY: dict[str, APIRouter] = {}
_DISCOVERED = False
_INTERNAL_MODULES = {"base", "health", "registry"}


def register_router(router: APIRouter, *, name: str | None = None) -> APIRouter:
    router_name = name or _router_name(router)
    if router_name in ROUTER_REGISTRY:
        raise ValueError(f"Router {router_name!r} is already registered")
    ROUTER_REGISTRY[router_name] = router
    return router


def registered_routers() -> dict[str, APIRouter]:
    return dict(ROUTER_REGISTRY)


def discover_routers() -> dict[str, APIRouter]:
    global _DISCOVERED
    if _DISCOVERED:
        return registered_routers()

    routers_dir = get_module_dir(__file__)
    for _, module_name, _ in pkgutil.iter_modules([str(routers_dir)]):
        if module_name.startswith("_") or module_name in _INTERNAL_MODULES:
            continue
        try:
            importlib.import_module(f"src.routers.{module_name}")
            logger.debug("Auto-imported router module: %s", module_name)
        except ImportError as e:
            logger.warning("Failed to import router module %s: %s", module_name, e)
    _DISCOVERED = True
    return registered_routers()


def include_registered_routers(app: FastAPI) -> None:
    for router in discover_routers().values():
        app.include_router(router)


def clear_registered_routers() -> None:
    global _DISCOVERED
    ROUTER_REGISTRY.clear()
    _DISCOVERED = False


def _router_name(router: APIRouter) -> str:
    if router.tags:
        return str(router.tags[0])
    if router.prefix:
        return router.prefix.strip("/").replace("/", "_")
    raise ValueError("Registered routers require a name, tag, or prefix")

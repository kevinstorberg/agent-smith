import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from config.loader import load_default_config
from src.agent_smith.integration import (
    include_agent_smith_routes,
    mount_agent_smith_frontend,
    start_agent_smith_runtime,
    stop_agent_smith_runtime,
)
from src.api.errors import RequestIDMiddleware, register_error_handlers
from src.diagnostics.router import create_diagnostics_router
from src.frontend.static import mount_frontend
from src.graphs.endpoints import create_graph_router
from src.jobs.router import create_jobs_router
from src.jobs.runtime import shutdown_job_runtime, start_job_runtime
from src.routers import health
from src.routers.health import _VERSION
from src.routers.registry import include_registered_routers
from src.security.middleware import RateLimitMiddleware, RequestBodySizeLimitMiddleware, SecurityHeadersMiddleware
from src.security.production import resolve_trusted_hosts, validate_production_settings
from src.settings import get_settings
from src.websockets.router import router as ws_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from cache.backends import get_cache_backend
    from memory.backends import get_backend

    # Startup
    if not hasattr(app.state, "config"):
        app.state.config = load_default_config()
    if not hasattr(app.state, "settings"):
        app.state.settings = get_settings()
    app.state.memory_backend = get_backend()
    app.state.cache_backend = get_cache_backend()

    # Trigger service auto-registration
    import src.services  # noqa: F401

    await start_job_runtime(app)
    if app.state.settings.AGENT_SMITH_ENABLED:
        await start_agent_smith_runtime(app)
    logger.info("App startup complete")

    yield

    # Shutdown
    if app.state.settings.AGENT_SMITH_ENABLED:
        await stop_agent_smith_runtime(app)
    await shutdown_job_runtime(app)

    if hasattr(app.state, "memory_backend"):
        backend = app.state.memory_backend
        if hasattr(backend, "close"):
            await backend.close()

    from db.connection import dispose_engine
    from src.graphs.checkpointing import reset_checkpointers

    await dispose_engine()
    reset_checkpointers()
    logger.info("App shutdown complete")


def create_app() -> FastAPI:
    config = load_default_config()
    settings = get_settings()
    production_errors = validate_production_settings(settings, config)
    if production_errors:
        joined_errors = "; ".join(production_errors)
        raise RuntimeError(f"Production security settings are invalid: {joined_errors}")

    application = FastAPI(title="Cairn", version=_VERSION, lifespan=lifespan)
    application.state.config = config
    application.state.settings = settings
    register_error_handlers(application)

    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=resolve_trusted_hosts(settings, config.security),
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.security.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(
        RequestBodySizeLimitMiddleware,
        max_body_bytes=config.security.max_request_body_bytes,
    )
    if config.security.rate_limit_enabled:
        application.add_middleware(
            RateLimitMiddleware,
            limit=config.security.rate_limit_requests,
            window_seconds=config.security.rate_limit_window_seconds,
        )
    application.add_middleware(
        SecurityHeadersMiddleware,
        headers_config=config.security.headers,
        hsts_enabled=settings.SECURE_HEADERS_HSTS_ENABLED,
    )
    application.add_middleware(RequestIDMiddleware)

    application.include_router(health.router, tags=["health"])
    application.include_router(create_graph_router())
    application.include_router(create_jobs_router())
    include_registered_routers(application)
    if settings.AGENT_SMITH_ENABLED:
        include_agent_smith_routes(application)
    if config.admin_debug.enabled:
        application.include_router(create_diagnostics_router(config=config, settings=settings))
    mount_frontend(application, config.frontend)
    application.include_router(ws_router)
    if settings.AGENT_SMITH_ENABLED:
        mount_agent_smith_frontend(application)
    return application


app = create_app()

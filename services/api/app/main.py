"""Misk API application factory.

/health has no dependency on anything: it answers 200 as long as the process is
alive, so an orchestrator never kills a pod because Postgres blinked.
/health/ready reports db, redis and s3 individually and returns 503 if any is
down — that is the signal that should remove an instance from a load balancer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import Settings, get_settings
from app.core.db import check_database, dispose_engine, init_engine
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.core.otel import configure_tracing, instrument_app
from app.core.redis import check_redis, dispose_redis, init_redis
from app.core.storage import check_storage

API_VERSION = "0.1.0"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, service=settings.service_name)
    configure_tracing(settings)
    logger = get_logger(__name__)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = init_engine(settings)
        init_redis(settings)
        instrument_app(app, engine=engine)
        logger.info("startup", environment=str(settings.environment))
        yield
        await dispose_engine()
        await dispose_redis()
        logger.info("shutdown")

    app = FastAPI(
        title="Misk API",
        version=API_VERSION,
        lifespan=lifespan,
        docs_url="/docs" if settings.debug_docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.debug_docs_enabled else None,
    )
    app.state.settings = settings

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
            expose_headers=["X-Request-Id"],
        )

    install_error_handlers(app)
    _install_health_routes(app, settings)
    _install_routers(app)
    return app


def _install_routers(app: FastAPI) -> None:
    from app.modules.children.router import router as children_router
    from app.modules.identity.router import router as identity_router

    app.include_router(identity_router)
    app.include_router(children_router)


def _install_health_routes(app: FastAPI, settings: Settings) -> None:
    @app.get("/health", tags=["health"], summary="Liveness — no dependencies")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": API_VERSION}

    @app.get("/health/ready", tags=["health"], summary="Readiness — per-dependency")
    async def health_ready() -> JSONResponse:
        checks: dict[str, Any] = {
            "db": await check_database(),
            "redis": await check_redis(),
            "s3": await check_storage(settings),
        }
        healthy = all(check["status"] == "ok" for check in checks.values())
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={"status": "ok" if healthy else "degraded", "checks": checks},
        )


app = create_app()

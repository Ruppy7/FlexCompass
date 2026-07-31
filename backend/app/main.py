"""FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

from .api_errors import (
    PublicExceptionMiddleware,
    http_exception_response,
    validation_exception_response,
)
from .config import config
from .db import run_migrations
from .demo_routes import demo_router
from .routes import OUTAGE_API_MIGRATION_MESSAGE, router

_VERSIONED_OUTAGE_STATIC_PATHS = {
    "/api/v1/outages/events",
    "/api/v1/outages/summary",
    "/api/v1/outages/snapshots",
}
_VERSIONED_OUTAGE_DETAIL_PREFIX = "/api/v1/outages/events/"
_LEGACY_OUTAGE_PREFIXES = ("/api/outages", "/api/outage-snapshots")


def _is_versioned_outage_path(path: str) -> bool:
    if path in _VERSIONED_OUTAGE_STATIC_PATHS:
        return True
    if not path.startswith(_VERSIONED_OUTAGE_DETAIL_PREFIX):
        return False
    event_id = path.removeprefix(_VERSIONED_OUTAGE_DETAIL_PREFIX)
    return bool(event_id) and "/" not in event_id


def _is_legacy_outage_path(path: str) -> bool:
    return any(
        path == prefix or path.startswith(f"{prefix}/")
        for prefix in _LEGACY_OUTAGE_PREFIXES
    )


class OutagePreflightContractMiddleware:
    """Keep outage method contracts ahead of global CORS preflight handling."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        headers = dict(scope.get("headers", ()))
        is_preflight = (
            scope["type"] == "http"
            and scope["method"] == "OPTIONS"
            and b"origin" in headers
            and b"access-control-request-method" in headers
        )
        if not is_preflight:
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        if _is_versioned_outage_path(path):
            response = JSONResponse(
                status_code=405,
                content={"detail": "Request failed", "code": "http_error"},
            )
            await response(scope, receive, send)
            return
        if _is_legacy_outage_path(path):
            response = JSONResponse(
                status_code=410,
                content={"detail": OUTAGE_API_MIGRATION_MESSAGE},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Prepare the configured outage store without coupling other databases."""
    run_migrations(config.outage_db_path)
    yield

app = FastAPI(
    title="FlexCompass",
    description=(
        "Independent open-source research API for public Great Britain "
        "electricity-network and flexibility-market data."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_exception_handler(
    RequestValidationError,
    validation_exception_response,
)
app.add_exception_handler(
    StarletteHTTPException,
    http_exception_response,
)

app.add_middleware(PublicExceptionMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.add_middleware(OutagePreflightContractMiddleware)

app.include_router(router)
app.include_router(demo_router)


@app.get("/")
def root_info() -> dict[str, object]:
    """Return service identity and the truthful public surface."""
    return {
        "service": "flexcompass",
        "version": "0.1.0",
        "description": "Public Great Britain grid-data research API",
        "endpoints": [
            "/health",
            "/api/health",
            "/api/demo/portfolios",
            "/api/demo/analyse",
            "/api/demo/report",
            "/api/demo/asset-groups/generate",
            "/api/v1/outages/events",
            "/api/v1/outages/summary",
            "/api/v1/outages/events/{event_id}",
            "/api/v1/outages/snapshots",
        ],
    }


@app.get("/health")
def root_health() -> dict[str, str | int]:
    return {
        "status": "ok",
        "service": "flexcompass",
        "version": "0.1.0",
        "seed": config.default_seed,
    }

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
from .catalogue_routes import router as catalogue_router
from .config import FlexCompassConfig, config
from .db import run_migrations
from .demo_routes import demo_router
from .routes import (
    CATALOGUE_API_MIGRATION_MESSAGE,
    OUTAGE_API_MIGRATION_MESSAGE,
    router,
)

_VERSIONED_OUTAGE_STATIC_PATHS = {
    "/api/v1/outages/events",
    "/api/v1/outages/summary",
    "/api/v1/outages/snapshots",
}
_VERSIONED_OUTAGE_DETAIL_PREFIX = "/api/v1/outages/events/"
_LEGACY_OUTAGE_PREFIXES = ("/api/outages", "/api/outage-snapshots")
_VERSIONED_CATALOGUE_STATIC_PATHS = {
    "/api/v1/catalogue/portals",
    "/api/v1/catalogue/datasets",
    "/api/v1/catalogue/observations",
}
_CATALOGUE_PORTAL_PREFIX = "/api/v1/catalogue/portals/"
_CATALOGUE_DATASET_PREFIX = "/api/v1/catalogue/datasets/"
_CATALOGUE_DATASET_CHILDREN = {"resources", "evidence", "assessments"}
_LEGACY_CATALOGUE_PATH = "/api/portal/datasets"


def _is_versioned_outage_path(path: str) -> bool:
    path = path.rstrip("/")
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


def _is_versioned_catalogue_path(path: str) -> bool:
    path = path.rstrip("/")
    if path in _VERSIONED_CATALOGUE_STATIC_PATHS:
        return True
    if path.startswith(_CATALOGUE_PORTAL_PREFIX):
        portal_id = path.removeprefix(_CATALOGUE_PORTAL_PREFIX)
        return bool(portal_id) and "/" not in portal_id
    if not path.startswith(_CATALOGUE_DATASET_PREFIX):
        return False
    remainder = path.removeprefix(_CATALOGUE_DATASET_PREFIX)
    parts = remainder.split("/")
    return bool(parts[0]) and (
        len(parts) == 1
        or (len(parts) == 2 and parts[1] in _CATALOGUE_DATASET_CHILDREN)
    )


class ReadOnlyPreflightContractMiddleware:
    """Keep path-aware read-only contracts ahead of global CORS handling."""

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
        if _is_versioned_outage_path(path) or _is_versioned_catalogue_path(path):
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
        if path.rstrip("/") == _LEGACY_CATALOGUE_PATH:
            response = JSONResponse(
                status_code=410,
                content={"detail": CATALOGUE_API_MIGRATION_MESSAGE},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app(settings: FlexCompassConfig | None = None) -> FastAPI:
    """Build an application whose dependencies use one injected configuration."""
    active_settings = settings or config

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        run_migrations(active_settings.outage_db_path)
        run_migrations(active_settings.catalogue_db_path)
        yield

    application = FastAPI(
        title="FlexCompass",
        description=(
            "Independent open-source research API for public Great Britain "
            "electricity-network and flexibility-market data."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = active_settings
    application.add_exception_handler(
        RequestValidationError,
        validation_exception_response,
    )
    application.add_exception_handler(
        StarletteHTTPException,
        http_exception_response,
    )
    application.add_middleware(PublicExceptionMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    application.add_middleware(ReadOnlyPreflightContractMiddleware)
    application.include_router(router)
    application.include_router(catalogue_router)
    application.include_router(demo_router)

    @application.get("/")
    def root_info() -> dict[str, object]:
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
                "/api/v1/catalogue/portals",
                "/api/v1/catalogue/portals/{portal_id}",
                "/api/v1/catalogue/datasets",
                "/api/v1/catalogue/datasets/{dataset_ref}",
                "/api/v1/catalogue/datasets/{dataset_ref}/resources",
                "/api/v1/catalogue/datasets/{dataset_ref}/evidence",
                "/api/v1/catalogue/datasets/{dataset_ref}/assessments",
                "/api/v1/catalogue/observations",
            ],
        }

    @application.get("/health")
    def root_health() -> dict[str, str | int]:
        return {
            "status": "ok",
            "service": "flexcompass",
            "version": "0.1.0",
            "seed": active_settings.default_seed,
        }

    return application


app = create_app()

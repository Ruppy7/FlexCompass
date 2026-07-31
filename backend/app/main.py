"""FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api_errors import (
    PublicExceptionMiddleware,
    http_exception_response,
    validation_exception_response,
)
from .config import config
from .db import run_migrations
from .demo_routes import demo_router
from .routes import router


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

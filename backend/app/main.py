"""FastAPI application entry point."""

from __future__ import annotations

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
from .demo_routes import demo_router
from .routes import router

app = FastAPI(
    title="FlexCompass",
    description=(
        "Independent open-source research API for public Great Britain "
        "electricity-network and flexibility-market data."
    ),
    version="0.1.0",
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
        "endpoints": ["/health", "/api/health"],
    }


@app.get("/health")
def root_health() -> dict[str, str | int]:
    return {
        "status": "ok",
        "service": "flexcompass",
        "version": "0.1.0",
        "seed": config.default_seed,
    }

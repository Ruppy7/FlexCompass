"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import config


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: run migrations, seed if needed, load data into caches."""
    from .db import run_migrations
    run_migrations()

    # Seed DB from JSON if the core tables are empty
    from .db import get_connection
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM portal_datasets").fetchone()[0]
    if count == 0:
        from .db_seed import seed_all
        seed_all()

    # Load data into route-level caches
    from .routes import reload_data
    reload_data()
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from .routes import router  # noqa: E402

app.include_router(router)


@app.get("/")
def root_info():
    """Root info — service identity + key stats."""
    return {
        "service": "flexcompass",
        "version": "0.1.0",
        "description": "Public Great Britain grid-data research API",
        "endpoints": [
            "/health",
            "/api/health",
            "/api/portal/datasets",
            "/api/zones",
            "/api/signals",
            "/api/portfolios",
            "/api/analyse",
            "/api/report",
            "/api/ingest/status",
            "/api/db/stats",
        ],
    }


@app.get("/health")
def root_health():
    return {
        "status": "ok",
        "service": "flexcompass",
        "version": "0.1.0",
        "seed": config.default_seed,
    }

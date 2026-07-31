"""Truthful read-only public API routes."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "data_status": "no_verified_analytical_data",
    }

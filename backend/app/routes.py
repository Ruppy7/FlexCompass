"""Truthful read-only public API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .config import FlexCompassConfig
from .outage_store import (
    count_outage_events,
    get_outage_event,
    list_outage_event_versions,
    list_source_snapshots,
    resolve_outage_evidence_scope,
    summarise_outage_events,
)
from .outages import (
    LicenceArea,
    OutageEvent,
    OutageEvidenceScopeV1,
    OutageSummary,
    SourceSnapshotPublic,
)

router = APIRouter(prefix="/api")
OUTAGE_API_MIGRATION_MESSAGE = "Outage API moved to /api/v1/outages."
CATALOGUE_API_MIGRATION_MESSAGE = "Use /api/v1/catalogue/datasets"
_LEGACY_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


class OutageEventPageV1(BaseModel):
    """One deterministic page from an explicit outage evidence scope."""

    items: list[OutageEvent]
    total: int
    limit: int
    offset: int
    evidence_scope: OutageEvidenceScopeV1


class OutageSummaryResponseV1(BaseModel):
    """Aggregate outage evidence and the immutable scope behind it."""

    summary: OutageSummary
    evidence_scope: OutageEvidenceScopeV1


def _evidence_scope(
    source_snapshot_ids: list[str] | None,
    settings: FlexCompassConfig,
) -> OutageEvidenceScopeV1:
    try:
        return resolve_outage_evidence_scope(
            source_snapshot_ids=source_snapshot_ids,
            db_path=settings.outage_db_path,
        )
    except ValueError as error:
        status_code = 503 if source_snapshot_ids is None else 422
        raise HTTPException(status_code=status_code) from error


@router.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "data_status": "verified_analytical_source_available_for_local_sync",
    }


@router.get(
    "/v1/outages/events",
    response_model=OutageEventPageV1,
)
def list_outage_api_events(
    request: Request,
    licence_area: Annotated[LicenceArea | None, Query()] = None,
    district_short_code: Annotated[str | None, Query(min_length=1)] = None,
    reporting_year: Annotated[int | None, Query(ge=1900, le=2100)] = None,
    cause_code: Annotated[str | None, Query(min_length=1)] = None,
    source_snapshot_id: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OutageEventPageV1:
    settings: FlexCompassConfig = request.app.state.settings
    evidence_scope = _evidence_scope(source_snapshot_id, settings)
    filters = {
        "licence_area": licence_area,
        "district_short_code": district_short_code,
        "reporting_year": reporting_year,
        "cause_code": cause_code,
    }
    items = list_outage_event_versions(
        evidence_scope.snapshot_ids,
        limit=limit,
        offset=offset,
        db_path=settings.outage_db_path,
        **filters,
    )
    total = count_outage_events(
        source_snapshot_ids=evidence_scope.snapshot_ids,
        db_path=settings.outage_db_path,
        **filters,
    )
    return OutageEventPageV1(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        evidence_scope=evidence_scope,
    )


@router.get(
    "/v1/outages/summary",
    response_model=OutageSummaryResponseV1,
)
def summarise_outage_api_events(
    request: Request,
    licence_area: Annotated[LicenceArea | None, Query()] = None,
    reporting_year: Annotated[int | None, Query(ge=1900, le=2100)] = None,
    source_snapshot_id: Annotated[list[str] | None, Query()] = None,
) -> OutageSummaryResponseV1:
    settings: FlexCompassConfig = request.app.state.settings
    evidence_scope = _evidence_scope(source_snapshot_id, settings)
    summary = summarise_outage_events(
        source_snapshot_ids=evidence_scope.snapshot_ids,
        licence_area=licence_area,
        reporting_year=reporting_year,
        db_path=settings.outage_db_path,
    )
    return OutageSummaryResponseV1(
        summary=summary,
        evidence_scope=evidence_scope,
    )


@router.get(
    "/v1/outages/snapshots",
    response_model=list[SourceSnapshotPublic],
)
def list_outage_api_snapshots(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SourceSnapshotPublic]:
    snapshots = list_source_snapshots(
        limit=limit,
        offset=offset,
        db_path=request.app.state.settings.outage_db_path,
    )
    return [
        SourceSnapshotPublic.model_validate(snapshot.model_dump())
        for snapshot in snapshots
    ]


@router.get(
    "/v1/outages/events/{event_id}",
    response_model=OutageEvent,
)
def get_outage_api_event(
    event_id: str,
    request: Request,
    source_snapshot_id: Annotated[
        list[str], Query(min_length=1, max_length=1)
    ],
) -> OutageEvent:
    try:
        event = get_outage_event(
            event_id,
            db_path=request.app.state.settings.outage_db_path,
            source_snapshot_ids=source_snapshot_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=422) from error
    if event is None:
        raise HTTPException(status_code=404)
    return event


@router.api_route(
    "/outages",
    methods=_LEGACY_METHODS,
    include_in_schema=False,
)
@router.api_route(
    "/outages/{legacy_path:path}",
    methods=_LEGACY_METHODS,
    include_in_schema=False,
)
@router.api_route(
    "/outage-snapshots",
    methods=_LEGACY_METHODS,
    include_in_schema=False,
)
@router.api_route(
    "/outage-snapshots/{legacy_path:path}",
    methods=_LEGACY_METHODS,
    include_in_schema=False,
)
def legacy_outage_api(legacy_path: str = "") -> JSONResponse:
    del legacy_path
    return JSONResponse(
        status_code=410,
        content={"detail": OUTAGE_API_MIGRATION_MESSAGE},
    )


@router.api_route(
    "/portal/datasets",
    methods=_LEGACY_METHODS,
    include_in_schema=False,
)
def legacy_catalogue_api() -> JSONResponse:
    """Retire the mutable legacy dataset surface without reading its rows."""
    return JSONResponse(
        status_code=410,
        content={"detail": CATALOGUE_API_MIGRATION_MESSAGE},
    )

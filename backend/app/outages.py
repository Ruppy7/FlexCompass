"""Canonical evidence contracts for public electricity-network outage data."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator

LicenceArea = Literal["SEPD", "SHEPD"]
NonEmptyStr = Annotated[str, Field(min_length=1)]


class SourceResource(BaseModel):
    """One public source resource accepted for outage ingestion."""

    source_dataset_id: NonEmptyStr
    package_id: NonEmptyStr
    source_resource_id: NonEmptyStr
    licence_area: LicenceArea
    name: str
    stable_url: str
    source_modified_at: datetime | None
    format: str
    media_type: str | None
    datastore_active: bool
    raw_record: dict[str, Any]


class SourceSnapshotPublic(BaseModel):
    """API-safe snapshot evidence without a local path or signed redirect URL."""

    snapshot_id: NonEmptyStr
    source_dataset_id: NonEmptyStr
    package_id: NonEmptyStr
    source_resource_id: NonEmptyStr
    licence_area: LicenceArea
    stable_source_url: str
    source_modified_at: datetime | None
    fetched_at: datetime
    content_sha256: NonEmptyStr
    byte_size: int
    row_count: int
    observed_columns: list[str]
    licence_id: str
    licence_title: str
    licence_url: str
    attribution: str
    parser_version: str

    @field_validator("fetched_at")
    @classmethod
    def normalise_fetched_at_to_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fetched_at must include a timezone")
        return value.astimezone(timezone.utc)


class SourceSnapshot(SourceSnapshotPublic):
    """A locally retained content-addressed snapshot manifest."""

    local_snapshot_path: str


class OutageEvent(BaseModel):
    """Canonical outage event with complete source and raw-row provenance."""

    event_id: NonEmptyStr
    source_dataset_id: NonEmptyStr
    source_resource_id: NonEmptyStr
    source_snapshot_id: NonEmptyStr
    operator: str
    licence_area: LicenceArea
    incident_started_local: str
    timezone_name: str | None
    reporting_year: int
    voltage_kv: float | None
    district_short_code: str
    district_hv_reference: str
    network_reference: str
    primary_nrn: str | None
    primary_name: str | None
    customers_affected: int | None
    customer_minutes_lost: int | None
    average_minutes_off_supply: float | None
    equipment_code: str | None
    equipment: str | None
    component_code: str | None
    component: str | None
    cause_code: str | None
    cause: str | None
    contributory_cause_code: str | None
    contributory_cause: str | None
    damage: str | None
    exceptional_event: str | None
    quality_flags: list[str]
    raw_record: dict[str, Any]


class OutageReject(BaseModel):
    """One rejected source row retained with a stable parsing error."""

    run_id: NonEmptyStr
    source_resource_id: NonEmptyStr
    row_number: int
    error_code: str
    error_message: str
    raw_row: dict[str, Any]


class SyncResult(BaseModel):
    """Summary of one local outage synchronisation attempt."""

    run_id: NonEmptyStr
    status: str
    resources_seen: int
    snapshots_created: int
    snapshots_reused: int
    events_written: int
    rejects_written: int
    warnings: list[str]


class OutageSummary(BaseModel):
    """Aggregate outage evidence for an explicitly filtered query."""

    event_count: int
    customers_affected_total: int | None
    customer_minutes_lost_total: int | None
    incident_started_local_min: str | None
    incident_started_local_max: str | None

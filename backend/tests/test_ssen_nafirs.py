"""Focused contracts for SSEN NaFIRS outage evidence models."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from app.outages import (
    OutageEvent,
    OutageReject,
    OutageSummary,
    SourceResource,
    SourceSnapshot,
    SourceSnapshotPublic,
    SyncResult,
)
from pydantic import ValidationError


def outage_event_data() -> dict[str, object]:
    return {
        "event_id": "ssen-hv:test",
        "source_dataset_id": "nafirs-hv-faults",
        "source_resource_id": "ab32515f-76f2-421d-8034-7d5b01325a33",
        "source_snapshot_id": "sha256:abc",
        "operator": "SSEN Distribution",
        "licence_area": "SEPD",
        "incident_started_local": "2026-07-12T16:33:00",
        "timezone_name": None,
        "reporting_year": 2026,
        "voltage_kv": 11.0,
        "district_short_code": "SWIN",
        "district_hv_reference": "55H000195",
        "network_reference": "55H000195_001",
        "primary_nrn": None,
        "primary_name": None,
        "customers_affected": 220,
        "customer_minutes_lost": None,
        "average_minutes_off_supply": None,
        "equipment_code": None,
        "equipment": None,
        "component_code": None,
        "component": None,
        "cause_code": "99",
        "cause": "Cause Unknown",
        "contributory_cause_code": None,
        "contributory_cause": None,
        "damage": None,
        "exceptional_event": None,
        "quality_flags": [],
        "raw_record": {"HV_INCIDENT_TIME": "12/07/2026  16:33"},
    }


def source_snapshot_data() -> dict[str, object]:
    return {
        "snapshot_id": "sha256:abc",
        "source_dataset_id": "nafirs-hv-faults",
        "package_id": "b0a58349-2ce6-4fa8-9238-a5564f966433",
        "source_resource_id": "ab32515f-76f2-421d-8034-7d5b01325a33",
        "licence_area": "SEPD",
        "stable_source_url": "https://data-api.ssen.co.uk/stable.csv",
        "source_modified_at": None,
        "fetched_at": datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
        "content_sha256": "abc",
        "byte_size": 128,
        "row_count": 1,
        "observed_columns": ["HV_INCIDENT_TIME"],
        "licence_id": "CC-BY-4.0",
        "licence_title": "Creative Commons Attribution 4.0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "SSEN Distribution",
        "parser_version": "1",
        "local_snapshot_path": "data/snapshots/ssen/nafirs-hv/example.csv",
    }


def test_outage_event_requires_complete_provenance() -> None:
    event = OutageEvent(**outage_event_data())

    assert event.source_snapshot_id == "sha256:abc"
    assert event.raw_record["HV_INCIDENT_TIME"].startswith("12/07/2026")


def test_outage_event_requires_nullable_evidence_to_be_explicit() -> None:
    data = outage_event_data()
    del data["timezone_name"]

    with pytest.raises(ValidationError, match="timezone_name"):
        OutageEvent(**data)


def test_outage_event_rejects_unknown_licence_area() -> None:
    data = outage_event_data()
    data["licence_area"] = "UNKNOWN"

    with pytest.raises(ValidationError, match="licence_area"):
        OutageEvent(**data)


@pytest.mark.parametrize(
    ("model", "data", "field"),
    [
        (
            SourceResource,
            {
                "source_dataset_id": "",
                "package_id": "package",
                "source_resource_id": "resource",
                "licence_area": "SEPD",
                "name": "NaFIRS HV Faults SEPD (CSV)",
                "stable_url": "https://data-api.ssen.co.uk/stable.csv",
                "source_modified_at": None,
                "format": "CSV",
                "media_type": None,
                "datastore_active": False,
                "raw_record": {},
            },
            "source_dataset_id",
        ),
        (SourceSnapshot, {**source_snapshot_data(), "source_resource_id": ""}, "source_resource_id"),
        (OutageEvent, {**outage_event_data(), "source_snapshot_id": ""}, "source_snapshot_id"),
    ],
)
def test_source_identity_fields_must_be_non_empty(
    model: type[SourceResource] | type[SourceSnapshot] | type[OutageEvent],
    data: dict[str, object],
    field: str,
) -> None:
    with pytest.raises(ValidationError, match=field):
        model(**data)


def test_source_snapshot_normalises_fetched_at_to_utc() -> None:
    data = source_snapshot_data()
    data["fetched_at"] = datetime(
        2026,
        7,
        30,
        17,
        30,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )

    snapshot = SourceSnapshot(**data)

    assert snapshot.fetched_at == datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
    assert snapshot.fetched_at.tzinfo is timezone.utc


def test_source_snapshot_rejects_naive_fetched_at() -> None:
    data = source_snapshot_data()
    data["fetched_at"] = datetime(2026, 7, 30, 12, 0)

    with pytest.raises(ValidationError, match="fetched_at"):
        SourceSnapshot(**data)


def test_public_snapshot_projection_omits_local_and_signed_urls() -> None:
    snapshot = SourceSnapshot(**source_snapshot_data())
    public = SourceSnapshotPublic(**snapshot.model_dump())

    assert public.source_resource_id == snapshot.source_resource_id
    assert "local_snapshot_path" not in SourceSnapshotPublic.model_fields
    assert "signed_redirect_url" not in SourceSnapshot.model_fields
    assert "signed_redirect_url" not in SourceSnapshotPublic.model_fields


def test_remaining_task_one_models_preserve_required_evidence() -> None:
    reject = OutageReject(
        run_id="run:test",
        source_resource_id="ab32515f-76f2-421d-8034-7d5b01325a33",
        row_number=2,
        error_code="invalid_timestamp",
        error_message="invalid local incident timestamp",
        raw_row={"HV_INCIDENT_TIME": "not-a-date"},
    )
    result = SyncResult(
        run_id="run:test",
        status="complete",
        resources_seen=2,
        snapshots_created=2,
        snapshots_reused=0,
        events_written=1,
        rejects_written=1,
        warnings=[],
    )
    summary = OutageSummary(
        event_count=1,
        customers_affected_total=220,
        customer_minutes_lost_total=None,
        incident_started_local_min="2026-07-12T16:33:00",
        incident_started_local_max="2026-07-12T16:33:00",
    )

    assert reject.row_number == 2
    assert result.resources_seen == 2
    assert summary.customer_minutes_lost_total is None

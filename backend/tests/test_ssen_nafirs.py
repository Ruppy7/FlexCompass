"""Focused contracts for SSEN NaFIRS outage evidence models."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import multiprocessing
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx
import pytest
from app.db import MIGRATIONS, get_connection, run_migrations
from app.outage_cli import main as outage_cli_main
from app.outage_source import (
    OwnedProcessSsenTransport,
    SourceLicenceEvidenceArtifactV1,
    _download_resource_in_child,
    _ssen_download_process_worker,
    download_ssen_hv_resource,
    load_ssen_source_manifest,
    sync_ssen_nafirs_hv,
)
from app.outage_store import (
    build_ssen_fetch_manifest,
    commit_ingestion_run,
    count_outage_events,
    count_source_snapshots,
    current_outage_snapshot_ids,
    get_outage_event,
    list_ingestion_run_snapshots,
    list_outage_event_versions,
    list_outage_events,
    list_source_snapshots,
    record_failed_ingestion_run,
    resolve_outage_evidence_scope,
    save_snapshot,
    source_observation_exists,
    summarise_outage_events,
    upsert_outage_events,
)
from app.outages import (
    OutageEvent,
    OutageFetchAttemptPublicV1,
    OutageReject,
    OutageSummary,
    SourceResource,
    SourceSnapshot,
    SourceSnapshotPublic,
    SyncResult,
    outage_reject_id,
    source_snapshot_id,
)
from app.persistence_safety import (
    MAX_CONTAINER_DEPTH,
    MAX_CONTAINER_ITEMS,
    MAX_PERSISTED_STRING_BYTES,
    MAX_STRUCTURED_VALUE_BYTES,
    UNSAFE_VALUE_SENTINEL,
    UnsafePersistenceValueError,
    require_exact_safe_raw_record,
    require_exact_safe_structure,
    sanitise_diagnostic_value,
)
from app.ssen_nafirs import (
    SEPD_COLUMNS,
    SHEPD_COLUMNS,
    OutageRowError,
    SourceContractError,
    discover_ssen_hv_resources,
    iter_ssen_hv_csv,
    parse_ssen_hv_event,
)
from pydantic import BaseModel, ValidationError

LicenceArea = Literal["SEPD", "SHEPD"]


def _spawn_success_worker(
    send_connection: Any,
    resource_payload: dict[str, Any],
    deadline: float,
) -> None:
    del resource_payload, deadline
    try:
        send_connection.send_bytes(b"Ocsv")
    finally:
        send_connection.close()


def _spawn_failure_worker(
    send_connection: Any,
    resource_payload: dict[str, Any],
    deadline: float,
) -> None:
    del resource_payload, deadline
    try:
        send_connection.send_bytes(b"E\x01\xff\xff")
    finally:
        send_connection.close()


def _spawn_non_cooperative_worker(
    send_connection: Any,
    resource_payload: dict[str, Any],
    deadline: float,
) -> None:
    del send_connection, resource_payload, deadline
    time.sleep(60)


def _spawn_malformed_worker(
    send_connection: Any,
    resource_payload: dict[str, Any],
    deadline: float,
) -> None:
    del resource_payload, deadline
    try:
        send_connection.send_bytes(b"not-a-valid-message")
    finally:
        send_connection.close()


def _spawn_duplicate_worker(
    send_connection: Any,
    resource_payload: dict[str, Any],
    deadline: float,
) -> None:
    del resource_payload, deadline
    try:
        send_connection.send_bytes(b"Ocsv")
        send_connection.send_bytes(b"Oduplicate")
    finally:
        send_connection.close()


def _spawn_oversize_worker(
    send_connection: Any,
    resource_payload: dict[str, Any],
    deadline: float,
) -> None:
    del resource_payload, deadline
    try:
        send_connection.send_bytes(b"O" + (b"x" * 64))
    finally:
        send_connection.close()


def _spawn_marker_failure_worker(
    send_connection: Any,
    resource_payload: dict[str, Any],
    deadline: float,
) -> None:
    del send_connection, resource_payload, deadline
    raise RuntimeError(
        "X-Amz-Signature=SYNTHETIC_CHILD_FAILURE_MUST_NOT_LEAK"
    )

EXPECTED_MODEL_FIELDS: dict[type[BaseModel], dict[str, object]] = {
    SourceResource: {
        "source_dataset_id": str,
        "package_id": str,
        "source_resource_id": str,
        "licence_area": LicenceArea,
        "name": str,
        "stable_url": str,
        "source_modified_at": datetime | None,
        "format": str,
        "media_type": str | None,
        "datastore_active": bool,
        "raw_record": dict[str, Any],
    },
    SourceSnapshot: {
        "snapshot_id": str,
        "source_dataset_id": str,
        "package_id": str,
        "source_resource_id": str,
        "licence_area": LicenceArea,
        "stable_source_url": str,
        "source_modified_at": datetime | None,
        "fetched_at": datetime | None,
        "content_sha256": str,
        "byte_size": int,
        "row_count": int,
        "observed_columns": list[str],
        "licence_id": str,
        "licence_title": str,
        "licence_url": str,
        "attribution": str,
        "parser_version": str,
        "local_snapshot_path": str,
    },
    SourceSnapshotPublic: {
        "snapshot_id": str,
        "source_dataset_id": str,
        "package_id": str,
        "source_resource_id": str,
        "licence_area": LicenceArea,
        "stable_source_url": str,
        "source_modified_at": datetime | None,
        "fetched_at": datetime | None,
        "content_sha256": str,
        "byte_size": int,
        "row_count": int,
        "observed_columns": list[str],
        "licence_id": str,
        "licence_title": str,
        "licence_url": str,
        "attribution": str,
        "parser_version": str,
    },
    OutageEvent: {
        "event_id": str,
        "source_dataset_id": str,
        "source_resource_id": str,
        "source_snapshot_id": str,
        "operator": str,
        "licence_area": LicenceArea,
        "incident_started_local": str,
        "timezone_name": str | None,
        "reporting_year": int,
        "voltage_kv": float | None,
        "district_short_code": str,
        "district_hv_reference": str,
        "network_reference": str,
        "primary_nrn": str | None,
        "primary_name": str | None,
        "customers_affected": int | None,
        "customer_minutes_lost": int | None,
        "average_minutes_off_supply": float | None,
        "equipment_code": str | None,
        "equipment": str | None,
        "component_code": str | None,
        "component": str | None,
        "cause_code": str | None,
        "cause": str | None,
        "contributory_cause_code": str | None,
        "contributory_cause": str | None,
        "damage": str | None,
        "exceptional_event": str | None,
        "quality_flags": list[str],
        "raw_record": dict[str, Any],
    },
    OutageReject: {
        "run_id": str,
        "source_resource_id": str,
        "row_number": int,
        "error_code": str,
        "error_message": str,
        "raw_row": dict[str, Any],
    },
    SyncResult: {
        "run_id": str,
        "status": str,
        "resources_seen": int,
        "snapshots_created": int,
        "snapshots_reused": int,
        "events_written": int,
        "rejects_written": int,
        "warnings": list[str],
    },
    OutageSummary: {
        "event_count": int,
        "customers_affected_total": int | None,
        "customer_minutes_lost_total": int | None,
        "incident_started_local_min": str | None,
        "incident_started_local_max": str | None,
    },
}

NON_EMPTY_IDENTITY_FIELDS: dict[type[BaseModel], set[str]] = {
    SourceResource: {"source_dataset_id", "package_id", "source_resource_id"},
    SourceSnapshot: {
        "snapshot_id",
        "source_dataset_id",
        "package_id",
        "source_resource_id",
        "content_sha256",
    },
    SourceSnapshotPublic: {
        "snapshot_id",
        "source_dataset_id",
        "package_id",
        "source_resource_id",
        "content_sha256",
    },
    OutageEvent: {
        "event_id",
        "source_dataset_id",
        "source_resource_id",
        "source_snapshot_id",
    },
    OutageReject: {"run_id", "source_resource_id"},
    SyncResult: {"run_id"},
}


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


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    return tmp_path / "outage-store.sqlite3"


@pytest.fixture
def parsed_event() -> OutageEvent:
    return OutageEvent(**outage_event_data())


@pytest.fixture
def source_snapshot() -> SourceSnapshot:
    return SourceSnapshot(**source_snapshot_data())


@pytest.mark.parametrize(("model", "expected_fields"), EXPECTED_MODEL_FIELDS.items())
def test_model_contract_has_exact_required_field_annotations(
    model: type[BaseModel],
    expected_fields: dict[str, object],
) -> None:
    assert list(model.model_fields) == list(expected_fields)
    for field_name, expected_annotation in expected_fields.items():
        field = model.model_fields[field_name]
        assert field.annotation == expected_annotation, field_name
        assert field.is_required(), field_name


@pytest.mark.parametrize(("model", "field_names"), NON_EMPTY_IDENTITY_FIELDS.items())
def test_every_identity_field_rejects_empty_strings(
    model: type[BaseModel],
    field_names: set[str],
) -> None:
    for field_name in field_names:
        field = model.model_fields[field_name]
        assert any(
            getattr(constraint, "min_length", None) == 1
            for constraint in field.metadata
        ), field_name


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


FIXTURES = Path(__file__).parent / "fixtures"
SEPD_RESOURCE_ID = "ab32515f-76f2-421d-8034-7d5b01325a33"
SHEPD_RESOURCE_ID = "673578c9-f531-41a5-a17c-0b35bc0fae4c"


@pytest.fixture
def sepd_csv_bytes() -> bytes:
    return (FIXTURES / "ssen_nafirs_hv_sepd_sample.csv").read_bytes()


@pytest.fixture
def shepd_csv_bytes() -> bytes:
    return (FIXTURES / "ssen_nafirs_hv_shepd_sample.csv").read_bytes()


@pytest.fixture
def sample_row(sepd_csv_bytes: bytes) -> dict[str, str]:
    return next(csv.DictReader(io.StringIO(sepd_csv_bytes.decode())))


@pytest.fixture
def shepd_sample_row(shepd_csv_bytes: bytes) -> dict[str, str]:
    return next(csv.DictReader(io.StringIO(shepd_csv_bytes.decode())))


def parse_sepd(row: dict[str, str]) -> OutageEvent:
    return parse_ssen_hv_event(
        row,
        licence_area="SEPD",
        source_dataset_id="nafirs-hv-faults",
        source_resource_id=SEPD_RESOURCE_ID,
        snapshot_id="sha256:test",
    )


def test_exact_area_headers_match_verified_raw_contracts() -> None:
    assert SEPD_COLUMNS == (
        "DISTRICT_SHORT_CODE",
        "REPORTING_YEAR",
        "VOLTAGE_1",
        "DIST_HV_REF",
        "HV_INCIDENT_TIME",
        "NRN_SOUTH",
        "EQUIPMENT_CODE",
        "EQUIPMENT",
        "COMPONENT_CODE",
        "COMPONENT",
        "CAUSE_CODE",
        "CAUSE",
        "CONTRIBUTORY_CAUSE_CODE",
        "CONTRIBUTORY_CAUSE",
        "DAMAGE",
        "EXCEPTIONAL_EVENT",
        "HV_CUST_AFF",
        "HV_CUST_MINS_LOST",
        "AVG_TIME_OFF_SUPPLY_MINS",
    )
    assert SHEPD_COLUMNS == (
        "DISTRICT_SHORT_CODE",
        "REPORTING_YEAR",
        "VOLTAGE_1",
        "DIST_HV_REF",
        "HV_INCIDENT_TIME",
        "NRN_NORTH",
        "PRIMARY_NRN",
        "PRIMARY_NAME",
        "EQUIPMENT_CODE",
        "EQUIPMENT",
        "COMPONENT_CODE",
        "COMPONENT",
        "CAUSE_CODE",
        "CAUSE",
        "CONTRIBUTORY_CAUSE_CODE",
        "CONTRIBUTORY_CAUSE",
        "DAMAGE",
        "EXCEPTIONAL_EVENT",
        "HV_CUST_AFF",
        "HV_CUST_MINS_LOST",
        "AVG_TIME_OFF_MINS",
    )


def test_day_first_timestamp_is_not_month_first(sample_row: dict[str, str]) -> None:
    event = parse_sepd(sample_row | {"HV_INCIDENT_TIME": "12/07/2026  16:33"})

    assert event.incident_started_local == "2026-07-12T16:33:00"
    assert event.timezone_name is None


def test_shepd_uses_north_reference_and_area_specific_average(
    shepd_sample_row: dict[str, str],
) -> None:
    event = parse_ssen_hv_event(
        shepd_sample_row,
        licence_area="SHEPD",
        source_dataset_id="nafirs-hv-faults",
        source_resource_id=SHEPD_RESOURCE_ID,
        snapshot_id="sha256:test",
    )

    assert event.network_reference == shepd_sample_row["NRN_NORTH"]
    assert event.average_minutes_off_supply == 111.0
    assert event.primary_nrn == shepd_sample_row["PRIMARY_NRN"]
    assert event.primary_name == shepd_sample_row["PRIMARY_NAME"]
    assert event.timezone_name is None


def test_parsed_values_are_normalised_but_raw_row_is_untouched(
    sample_row: dict[str, str],
) -> None:
    row = sample_row | {
        "DISTRICT_SHORT_CODE": "  OXFS \t",
        "CAUSE": "  Operational   or\nSafety Restriction ",
        "HV_INCIDENT_TIME": "14/04/2024  18:12",
    }

    event = parse_sepd(row)

    assert event.district_short_code == "OXFS"
    assert event.cause == "Operational or Safety Restriction"
    assert event.raw_record == row
    assert event.raw_record["DISTRICT_SHORT_CODE"] == "  OXFS \t"
    assert event.raw_record["HV_INCIDENT_TIME"] == "14/04/2024  18:12"


def test_event_id_uses_canonical_raw_evidence(sample_row: dict[str, str]) -> None:
    row = sample_row | {"HV_INCIDENT_TIME": "12/07/2026  16:33"}
    canonical_json = (
        '{"district_hv_reference":"43H000017",'
        '"incident_time":"12/07/2026  16:33",'
        '"licence_area":"SEPD","network_reference":"4905004",'
        '"source_dataset_id":"nafirs-hv-faults",'
        '"source_resource_id":"ab32515f-76f2-421d-8034-7d5b01325a33"}'
    )

    assert parse_sepd(row).event_id == hashlib.sha256(
        canonical_json.encode()
    ).hexdigest()


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("DISTRICT_SHORT_CODE", "", "missing_required_field"),
        ("DIST_HV_REF", " \t", "missing_required_field"),
        ("NRN_SOUTH", "", "missing_required_field"),
        ("REPORTING_YEAR", "", "missing_required_field"),
        ("REPORTING_YEAR", "2024.0", "invalid_reporting_year"),
        ("REPORTING_YEAR", "1899", "invalid_reporting_year"),
        ("REPORTING_YEAR", "2101", "invalid_reporting_year"),
        ("HV_INCIDENT_TIME", "", "missing_required_field"),
        ("HV_INCIDENT_TIME", "07/12/2026 16:33:00", "invalid_incident_time"),
        ("HV_INCIDENT_TIME", "31/02/2026 16:33", "invalid_incident_time"),
    ],
)
def test_required_field_rejects_have_stable_codes(
    sample_row: dict[str, str],
    field: str,
    value: str,
    code: str,
) -> None:
    with pytest.raises(OutageRowError) as caught:
        parse_sepd(sample_row | {field: value})

    assert caught.value.code == code
    assert caught.value.message
    if value:
        assert value not in caught.value.message


def test_oversized_reporting_year_has_stable_row_error(
    sample_row: dict[str, str],
) -> None:
    with pytest.raises(OutageRowError) as caught:
        parse_sepd(sample_row | {"REPORTING_YEAR": "9" * 5000})

    assert caught.value.code == "invalid_reporting_year"


@pytest.mark.parametrize(
    ("field", "value", "attribute", "flag"),
    [
        ("VOLTAGE_1", "not-a-number", "voltage_kv", "invalid_voltage_kv"),
        ("VOLTAGE_1", "nan", "voltage_kv", "invalid_voltage_kv"),
        ("VOLTAGE_1", "0", "voltage_kv", "invalid_voltage_kv"),
        ("HV_CUST_AFF", "1.5", "customers_affected", "invalid_customers_affected"),
        ("HV_CUST_AFF", "-1", "customers_affected", "invalid_customers_affected"),
        (
            "HV_CUST_MINS_LOST",
            "inf",
            "customer_minutes_lost",
            "invalid_customer_minutes_lost",
        ),
        (
            "HV_CUST_MINS_LOST",
            "-1",
            "customer_minutes_lost",
            "invalid_customer_minutes_lost",
        ),
        (
            "AVG_TIME_OFF_SUPPLY_MINS",
            "-0.1",
            "average_minutes_off_supply",
            "invalid_average_minutes_off_supply",
        ),
        (
            "AVG_TIME_OFF_SUPPLY_MINS",
            "NaN",
            "average_minutes_off_supply",
            "invalid_average_minutes_off_supply",
        ),
    ],
)
def test_invalid_optional_numeric_values_become_flagged_unknowns(
    sample_row: dict[str, str],
    field: str,
    value: str,
    attribute: str,
    flag: str,
) -> None:
    event = parse_sepd(sample_row | {field: value})

    assert getattr(event, attribute) is None
    assert event.quality_flags == [flag]


@pytest.mark.parametrize(
    ("field", "attribute", "flag"),
    [
        ("HV_CUST_AFF", "customers_affected", "invalid_customers_affected"),
        (
            "HV_CUST_MINS_LOST",
            "customer_minutes_lost",
            "invalid_customer_minutes_lost",
        ),
    ],
)
def test_oversized_optional_integer_is_a_flagged_unknown(
    sample_row: dict[str, str],
    field: str,
    attribute: str,
    flag: str,
) -> None:
    event = parse_sepd(sample_row | {field: "9" * 5000})

    assert getattr(event, attribute) is None
    assert event.quality_flags == [flag]


@pytest.mark.parametrize(
    ("field", "attribute"),
    [
        ("VOLTAGE_1", "voltage_kv"),
        ("HV_CUST_AFF", "customers_affected"),
        ("HV_CUST_MINS_LOST", "customer_minutes_lost"),
        ("AVG_TIME_OFF_SUPPLY_MINS", "average_minutes_off_supply"),
        ("CONTRIBUTORY_CAUSE_CODE", "contributory_cause_code"),
        ("CONTRIBUTORY_CAUSE", "contributory_cause"),
    ],
)
def test_blank_optional_values_are_unflagged_unknowns(
    sample_row: dict[str, str],
    field: str,
    attribute: str,
) -> None:
    event = parse_sepd(sample_row | {field: " \t"})

    assert getattr(event, attribute) is None
    assert event.quality_flags == []


@pytest.mark.parametrize(
    "header_mutation",
    [
        lambda columns: columns[:-1],
        lambda columns: (*columns, "EXTRA"),
        lambda columns: (*columns[:-1], "AVG_TIME_OFF_MINS"),
        lambda columns: (columns[1], columns[0], *columns[2:]),
    ],
)
def test_header_contract_fails_closed_with_observed_header(
    header_mutation: Any,
) -> None:
    observed = header_mutation(SEPD_COLUMNS)
    csv_bytes = (",".join(observed) + "\n").encode()

    with pytest.raises(SourceContractError) as caught:
        list(iter_ssen_hv_csv(csv_bytes, licence_area="SEPD"))

    assert list(observed) == caught.value.observed


def test_one_bad_row_does_not_block_later_valid_row(
    sepd_csv_bytes: bytes,
) -> None:
    lines = sepd_csv_bytes.decode().splitlines()
    bad_shape = ",".join(lines[1].split(",")[:-1])
    csv_bytes = "\n".join((lines[0], bad_shape, lines[2])).encode()

    results = list(
        iter_ssen_hv_csv(
            csv_bytes,
            licence_area="SEPD",
            source_dataset_id="nafirs-hv-faults",
            source_resource_id=SEPD_RESOURCE_ID,
            snapshot_id="sha256:test",
        )
    )

    assert len(results) == 2
    assert isinstance(results[0], OutageRowError)
    assert results[0].code == "invalid_row_shape"
    assert isinstance(results[1], OutageEvent)
    assert results[1].incident_started_local == "2026-07-12T16:15:00"


@pytest.mark.parametrize(
    ("field", "expected_type", "expected_flag"),
    [
        ("REPORTING_YEAR", OutageRowError, None),
        ("HV_CUST_AFF", OutageEvent, "invalid_customers_affected"),
        (
            "HV_CUST_MINS_LOST",
            OutageEvent,
            "invalid_customer_minutes_lost",
        ),
    ],
)
def test_oversized_integer_row_does_not_block_later_valid_row(
    sepd_csv_bytes: bytes,
    field: str,
    expected_type: type[OutageRowError] | type[OutageEvent],
    expected_flag: str | None,
) -> None:
    parsed_rows = list(csv.reader(io.StringIO(sepd_csv_bytes.decode())))
    field_index = parsed_rows[0].index(field)
    parsed_rows[1][field_index] = "9" * 5000
    csv_text = io.StringIO(newline="")
    csv.writer(csv_text, lineterminator="\n").writerows(parsed_rows)

    results = list(
        iter_ssen_hv_csv(
            csv_text.getvalue().encode(),
            licence_area="SEPD",
            source_resource_id=SEPD_RESOURCE_ID,
            snapshot_id="sha256:test",
        )
    )

    assert len(results) == 2
    assert isinstance(results[0], expected_type)
    if expected_flag is None:
        assert isinstance(results[0], OutageRowError)
        assert results[0].code == "invalid_reporting_year"
    else:
        assert isinstance(results[0], OutageEvent)
        assert results[0].quality_flags == [expected_flag]
    assert isinstance(results[1], OutageEvent)
    assert results[1].incident_started_local == "2026-07-12T16:15:00"


def test_lexically_malformed_row_does_not_drop_later_valid_row(
    sepd_csv_bytes: bytes,
) -> None:
    lines = sepd_csv_bytes.decode().splitlines()
    malformed = lines[1].replace("Switchgear", '"bad"tail', 1)
    csv_bytes = "\n".join((lines[0], malformed, lines[2])).encode()

    results = list(
        iter_ssen_hv_csv(
            csv_bytes,
            licence_area="SEPD",
            source_resource_id=SEPD_RESOURCE_ID,
            snapshot_id="sha256:test",
        )
    )

    assert len(results) == 2
    assert isinstance(results[0], OutageRowError)
    assert results[0].code == "invalid_row_shape"
    assert results[0].row_number == 2
    assert isinstance(results[1], OutageEvent)
    assert results[1].incident_started_local == "2026-07-12T16:15:00"


def package_client(
    package: dict[str, Any],
    requests: list[httpx.Request],
    *,
    follow_redirects: bool = False,
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=package)

    return httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=follow_redirects,
    )


@pytest.fixture
def package_show() -> dict[str, Any]:
    return json.loads(
        (FIXTURES / "ssen_nafirs_package_show.json").read_text(encoding="utf-8")
    )


def test_discovery_uses_one_non_redirecting_package_get_and_returns_exact_csvs(
    package_show: dict[str, Any],
) -> None:
    requests: list[httpx.Request] = []
    with package_client(package_show, requests) as client:
        resources = discover_ssen_hv_resources(client)

    assert [(item.licence_area, item.source_resource_id) for item in resources] == [
        ("SEPD", SEPD_RESOURCE_ID),
        ("SHEPD", SHEPD_RESOURCE_ID),
    ]
    assert resources[0].raw_record == package_show["result"]["resources"][0]
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == (
        "https://data-api.ssen.co.uk/api/3/action/"
        "package_show?id=nafirs-hv-faults"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda package: package.update(success=False),
        lambda package: package["result"].update(id="wrong"),
        lambda package: package["result"].update(license_id="wrong"),
        lambda package: package["result"].update(license_title="wrong"),
        lambda package: package["result"].update(license_url="https://wrong.example/"),
        lambda package: package["result"]["resources"].pop(0),
        lambda package: package["result"]["resources"].append(
            {
                **package["result"]["resources"][0],
                "id": "additional-active-csv",
            }
        ),
        lambda package: package["result"]["resources"].append(
            {
                **package["result"]["resources"][0],
                "id": "additional-lowercase-csv",
                "format": "csv",
            }
        ),
        lambda package: package["result"]["resources"].append(
            {
                **package["result"]["resources"][0],
                "id": "additional-media-type-csv",
                "format": "",
                "mimetype": "text/csv; charset=utf-8",
            }
        ),
        lambda package: package["result"]["resources"][0].update(name="renamed"),
        lambda package: package["result"]["resources"][0].update(id="replaced"),
        lambda package: package["result"]["resources"][0].update(
            url="https://evil.example/file.csv"
        ),
        lambda package: package["result"]["resources"][0].update(
            url=(
                "https://data-api.ssen.co.uk/dataset/wrong-package/resource/"
                f"{SEPD_RESOURCE_ID}/download/mutable.csv"
            )
        ),
    ],
)
def test_discovery_fails_closed_on_package_or_resource_drift(
    package_show: dict[str, Any],
    mutation: Any,
) -> None:
    mutation(package_show)
    with package_client(package_show, []) as client:
        with pytest.raises(SourceContractError):
            discover_ssen_hv_resources(client)


def test_discovery_rejects_redirect_following_client(
    package_show: dict[str, Any],
) -> None:
    with package_client(package_show, [], follow_redirects=True) as client:
        with pytest.raises(SourceContractError, match="redirect"):
            discover_ssen_hv_resources(client)


def test_discovery_accepts_mutable_dated_filename(
    package_show: dict[str, Any],
) -> None:
    package_show["result"]["resources"][0]["url"] = (
        "https://data-api.ssen.co.uk/dataset/"
        "b0a58349-2ce6-4fa8-9238-a5564f966433/resource/"
        f"{SEPD_RESOURCE_ID}/download/20300101_new_name.csv"
    )

    with package_client(package_show, []) as client:
        resources = discover_ssen_hv_resources(client)

    assert resources[0].stable_url.endswith("/20300101_new_name.csv")


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        (
            "last_modified",
            "https://example.invalid/?X-Amz-Signature="
            "SYNTHETIC_SIGNATURE_MUST_NOT_LEAK",
        ),
        (
            "mimetype",
            {"X-Amz-Signature": "SYNTHETIC_SIGNATURE_MUST_NOT_LEAK"},
        ),
    ],
)
def test_discovery_wraps_invalid_resource_model_fields_without_leakage(
    package_show: dict[str, Any],
    field: str,
    invalid_value: Any,
) -> None:
    package_show["result"]["resources"][0][field] = invalid_value

    with package_client(package_show, []) as client:
        with pytest.raises(SourceContractError) as caught:
            discover_ssen_hv_resources(client)

    assert "SYNTHETIC_SIGNATURE_MUST_NOT_LEAK" not in str(caught.value)
    assert "X-Amz-Signature" not in str(caught.value)


def _install_schema_through_five(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        for version, ddl in MIGRATIONS[:5]:
            connection.executescript(ddl)
            connection.execute(
                "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
                (version,),
            )
        connection.commit()


def _snapshot_with(
    snapshot: SourceSnapshot,
    *,
    snapshot_id: str,
    fetched_at: datetime,
    resource_id: str | None = None,
) -> SourceSnapshot:
    return snapshot.model_copy(
        update={
            "snapshot_id": snapshot_id,
            "content_sha256": snapshot_id.removeprefix("sha256:"),
            "fetched_at": fetched_at,
            "source_resource_id": resource_id or snapshot.source_resource_id,
        }
    )


def _event_with(
    event: OutageEvent,
    *,
    event_id: str,
    snapshot_id: str,
    incident_started_local: str,
    licence_area: Literal["SEPD", "SHEPD"] = "SEPD",
    district_short_code: str = "SWIN",
    reporting_year: int = 2026,
    cause_code: str | None = "99",
    customers_affected: int | None = 220,
    customer_minutes_lost: int | None = None,
) -> OutageEvent:
    return event.model_copy(
        update={
            "event_id": event_id,
            "source_snapshot_id": snapshot_id,
            "incident_started_local": incident_started_local,
            "licence_area": licence_area,
            "district_short_code": district_short_code,
            "reporting_year": reporting_year,
            "cause_code": cause_code,
            "customers_affected": customers_affected,
            "customer_minutes_lost": customer_minutes_lost,
        }
    )


def _exact_run_payload(
    source_snapshot: SourceSnapshot,
    parsed_event: OutageEvent,
    *,
    run_id: str,
) -> dict[str, Any]:
    fetched_at = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    sepd_digest = "a" * 64
    shepd_digest = "b" * 64
    sepd = source_snapshot.model_copy(
        update={
            "snapshot_id": source_snapshot_id(SEPD_RESOURCE_ID, sepd_digest),
            "source_resource_id": SEPD_RESOURCE_ID,
            "licence_area": "SEPD",
            "content_sha256": sepd_digest,
            "byte_size": 101,
            "fetched_at": fetched_at,
            "local_snapshot_path": f"blobs/aa/{sepd_digest}.csv",
        }
    )
    shepd = source_snapshot.model_copy(
        update={
            "snapshot_id": source_snapshot_id(SHEPD_RESOURCE_ID, shepd_digest),
            "source_resource_id": SHEPD_RESOURCE_ID,
            "licence_area": "SHEPD",
            "content_sha256": shepd_digest,
            "byte_size": 202,
            "row_count": 0,
            "fetched_at": fetched_at,
            "local_snapshot_path": f"blobs/bb/{shepd_digest}.csv",
        }
    )
    event = parsed_event.model_copy(
        update={
            "source_snapshot_id": sepd.snapshot_id,
            "source_resource_id": SEPD_RESOURCE_ID,
            "licence_area": "SEPD",
        }
    )
    attempts = [
        OutageFetchAttemptPublicV1(
            attempt_id=f"attempt:{run_id}:{snapshot.source_resource_id}",
            run_id=run_id,
            source_resource_id=snapshot.source_resource_id,
            attempted_at=fetched_at,
            status="completed",
            response_status=200,
            source_modified_at=snapshot.source_modified_at,
            source_snapshot_id=snapshot.snapshot_id,
            content_sha256=snapshot.content_sha256,
            byte_size=snapshot.byte_size,
            error_code=None,
        )
        for snapshot in (sepd, shepd)
    ]
    return {
        "run_id": run_id,
        "resources_seen": 2,
        "snapshots": [sepd, shepd],
        "events": [event],
        "rejects": [],
        "warnings": [],
        "fetch_attempts": attempts,
    }


def _commit_exact_run(
    source_snapshot: SourceSnapshot,
    parsed_event: OutageEvent,
    *,
    run_id: str,
    db_path: Path,
    rejects: list[OutageReject] | None = None,
    warnings: list[Any] | None = None,
) -> SyncResult:
    payload = _exact_run_payload(
        source_snapshot,
        parsed_event,
        run_id=run_id,
    )
    if rejects is not None:
        payload["rejects"] = rejects
    if warnings is not None:
        payload["warnings"] = warnings
    row_counts = {
        snapshot.source_resource_id: 0 for snapshot in payload["snapshots"]
    }
    for event in payload["events"]:
        row_counts[event.source_resource_id] += 1
    for reject in payload["rejects"]:
        row_counts[reject.source_resource_id] += 1
    payload["snapshots"] = [
        snapshot.model_copy(
            update={"row_count": row_counts[snapshot.source_resource_id]}
        )
        for snapshot in payload["snapshots"]
    ]
    return commit_ingestion_run(**payload, db_path=db_path)


def test_outage_schema_migrates_with_required_tables_and_indexes(
    temp_db: Path,
) -> None:
    assert run_migrations(temp_db) == 7
    with get_connection(temp_db) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        snapshot_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(source_snapshots)")
        }
        event_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(outage_events)")
        }

    assert {
        "source_snapshots",
        "ingestion_runs",
        "outage_events",
        "outage_rejects",
    } <= tables
    assert {
        "idx_outage_events_area_year",
        "idx_outage_events_district",
        "idx_outage_events_cause",
        "idx_outage_events_incident",
    } <= indexes
    assert "signed_redirect_url" not in snapshot_columns
    assert {"raw_record_json", "quality_flags_json"} <= event_columns


def test_migration_six_upgrades_populated_version_five_without_data_loss(
    temp_db: Path,
) -> None:
    _install_schema_through_five(temp_db)
    with sqlite3.connect(temp_db) as connection:
        connection.execute(
            """INSERT INTO portal_datasets (id, name, portal_url)
               VALUES (?, ?, ?)""",
            ("legacy", "Legacy public fixture", "https://example.invalid/legacy"),
        )
        connection.commit()

    assert run_migrations(temp_db) == 7
    assert run_migrations(temp_db) == 7
    with get_connection(temp_db) as connection:
        row = connection.execute(
            "SELECT name FROM portal_datasets WHERE id = ?", ("legacy",)
        ).fetchone()
        foreign_key_errors = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

    assert row[0] == "Legacy public fixture"
    assert foreign_key_errors == []


def test_migration_six_rolls_back_every_new_object_and_version_on_failure(
    temp_db: Path,
) -> None:
    _install_schema_through_five(temp_db)
    with sqlite3.connect(temp_db) as connection:
        connection.execute("CREATE TABLE outage_events (placeholder TEXT)")
        connection.commit()

    with pytest.raises(sqlite3.OperationalError):
        run_migrations(temp_db)

    with sqlite3.connect(temp_db) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        versions = {
            row[0]
            for row in connection.execute("SELECT version FROM schema_version")
        }

    assert "outage_events" in tables
    assert {
        "source_snapshots",
        "ingestion_runs",
        "outage_rejects",
    }.isdisjoint(tables)
    assert 6 not in versions


def test_snapshot_round_trip_filters_pages_and_omits_signed_urls(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
) -> None:
    newest = _snapshot_with(
        source_snapshot,
        snapshot_id="sha256:newest",
        fetched_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
    )
    second = _snapshot_with(
        source_snapshot,
        snapshot_id="sha256:second",
        fetched_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
    )
    third = _snapshot_with(
        source_snapshot,
        snapshot_id="sha256:third",
        fetched_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        resource_id=SHEPD_RESOURCE_ID,
    )
    for snapshot in (second, third, newest):
        save_snapshot(snapshot, db_path=temp_db)

    assert count_source_snapshots(db_path=temp_db) == 3
    assert count_source_snapshots(
        source_resource_id=SHEPD_RESOURCE_ID, db_path=temp_db
    ) == 1
    assert [item.snapshot_id for item in list_source_snapshots(
        source_resource_id=SHEPD_RESOURCE_ID, db_path=temp_db
    )] == ["sha256:third"]
    assert [item.snapshot_id for item in list_source_snapshots(
        limit=2, offset=0, db_path=temp_db
    )] == ["sha256:newest", "sha256:second"]
    assert [item.snapshot_id for item in list_source_snapshots(
        limit=2, offset=2, db_path=temp_db
    )] == ["sha256:third"]
    assert list_source_snapshots(limit=2, offset=3, db_path=temp_db) == []
    assert list_source_snapshots(limit=2, offset=10, db_path=temp_db) == []
    public = SourceSnapshotPublic(
        **list_source_snapshots(limit=1, db_path=temp_db)[0].model_dump()
    ).model_dump(mode="json")
    assert "local_snapshot_path" not in public
    assert "signed_redirect_url" not in json.dumps(public)


def test_snapshot_store_rejects_signed_redirect_provenance(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
) -> None:
    signed = source_snapshot.model_copy(
        update={
            "stable_source_url": (
                "https://data-api.ssen.co.uk/stable.csv?"
                "X-Amz-Signature=SYNTHETIC_SIGNATURE_MUST_NOT_PERSIST"
            )
        }
    )

    with pytest.raises(ValueError, match="stable SSEN"):
        save_snapshot(signed, db_path=temp_db)

    assert count_source_snapshots(db_path=temp_db) == 0


@pytest.mark.parametrize("limit", [0, 1001])
def test_outage_and_snapshot_queries_reject_limits_outside_contract(
    temp_db: Path,
    limit: int,
) -> None:
    with pytest.raises(ValueError, match="limit"):
        list_outage_events(limit=limit, db_path=temp_db)
    with pytest.raises(ValueError, match="limit"):
        list_source_snapshots(limit=limit, db_path=temp_db)


def test_event_version_helper_round_trips_json_and_rejects_mutation(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
    parsed_event: OutageEvent,
) -> None:
    save_snapshot(source_snapshot, db_path=temp_db)
    first = parsed_event.model_copy(
        update={
            "quality_flags": ["invalid_customers_affected"],
            "raw_record": {"HV_INCIDENT_TIME": "12/07/2026  16:33", "v": 1},
        }
    )
    updated = first.model_copy(
        update={
            "cause": "Updated public evidence",
            "quality_flags": [],
            "raw_record": {"HV_INCIDENT_TIME": "12/07/2026  16:33", "v": 2},
        }
    )

    assert upsert_outage_events([first], db_path=temp_db) == 1
    with pytest.raises(ValueError, match="immutable"):
        upsert_outage_events([updated], db_path=temp_db)

    snapshot_ids = (source_snapshot.snapshot_id,)
    rows = list_outage_events(
        source_snapshot_ids=snapshot_ids, db_path=temp_db
    )
    assert len(rows) == 1
    assert rows[0] == first
    assert get_outage_event(
        first.event_id,
        db_path=temp_db,
        source_snapshot_ids=snapshot_ids,
    ) == first
    assert get_outage_event(
        "missing", db_path=temp_db, source_snapshot_ids=snapshot_ids
    ) is None


def test_event_queries_share_filters_and_have_deterministic_page_boundaries(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
    parsed_event: OutageEvent,
) -> None:
    save_snapshot(source_snapshot, db_path=temp_db)
    events = [
        _event_with(
            parsed_event,
            event_id="event-c",
            snapshot_id=source_snapshot.snapshot_id,
            incident_started_local="2026-07-03T00:00:00",
            district_short_code="NORTH",
            cause_code=None,
        ),
        _event_with(
            parsed_event,
            event_id="event-b",
            snapshot_id=source_snapshot.snapshot_id,
            incident_started_local="2026-07-02T00:00:00",
            licence_area="SHEPD",
            reporting_year=2025,
            cause_code="11",
        ),
        _event_with(
            parsed_event,
            event_id="event-a",
            snapshot_id=source_snapshot.snapshot_id,
            incident_started_local="2026-07-02T00:00:00",
        ),
    ]
    upsert_outage_events(events, db_path=temp_db)
    snapshot_ids = (source_snapshot.snapshot_id,)

    assert [item.event_id for item in list_outage_events(
        source_snapshot_ids=snapshot_ids, limit=2, offset=0, db_path=temp_db
    )] == ["event-a", "event-b"]
    assert [item.event_id for item in list_outage_events(
        source_snapshot_ids=snapshot_ids, limit=2, offset=2, db_path=temp_db
    )] == ["event-c"]
    assert list_outage_events(
        source_snapshot_ids=snapshot_ids, limit=2, offset=3, db_path=temp_db
    ) == []
    assert list_outage_events(
        source_snapshot_ids=snapshot_ids, limit=2, offset=9, db_path=temp_db
    ) == []
    filters = {
        "licence_area": "SHEPD",
        "district_short_code": "SWIN",
        "reporting_year": 2025,
        "cause_code": "11",
        "source_snapshot_ids": snapshot_ids,
        "db_path": temp_db,
    }
    assert count_outage_events(**filters) == 1
    assert [item.event_id for item in list_outage_events(**filters)] == ["event-b"]
    assert summarise_outage_events(
        source_snapshot_ids=snapshot_ids,
        licence_area="SHEPD",
        reporting_year=2025,
        db_path=temp_db,
    ).customers_affected_total == 220


def test_summary_preserves_all_null_sums(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
    parsed_event: OutageEvent,
) -> None:
    save_snapshot(source_snapshot, db_path=temp_db)
    event = _event_with(
        parsed_event,
        event_id="null-metrics",
        snapshot_id=source_snapshot.snapshot_id,
        incident_started_local="2026-07-02T00:00:00",
        customers_affected=None,
        customer_minutes_lost=None,
    )
    upsert_outage_events([event], db_path=temp_db)

    summary = summarise_outage_events(
        source_snapshot_ids=(source_snapshot.snapshot_id,),
        licence_area="SEPD",
        reporting_year=2026,
        db_path=temp_db,
    )

    assert summary == OutageSummary(
        event_count=1,
        customers_affected_total=None,
        customer_minutes_lost_total=None,
        incident_started_local_min="2026-07-02T00:00:00",
        incident_started_local_max="2026-07-02T00:00:00",
    )


def test_commit_ingestion_run_is_one_atomic_transaction(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
    parsed_event: OutageEvent,
) -> None:
    marker = "SYNTHETIC_SIGNATURE_MUST_NOT_PERSIST"
    reject = OutageReject(
        run_id="run:complete",
        source_resource_id=source_snapshot.source_resource_id,
        row_number=2,
        error_code="invalid_incident_time",
        error_message="invalid local incident timestamp",
        raw_row={"HV_INCIDENT_TIME": "not-a-date", "signed_url": marker},
    )

    result = _commit_exact_run(
        source_snapshot,
        parsed_event,
        run_id="run:complete",
        db_path=temp_db,
        rejects=[reject],
        warnings=["publisher cadence remains unknown"],
    )

    assert result.status == "completed"
    assert result.events_written == 1
    assert result.rejects_written == 1
    with get_connection(temp_db) as connection:
        run = connection.execute(
            "SELECT status FROM ingestion_runs WHERE run_id = ?", ("run:complete",)
        ).fetchone()
        reject_json = connection.execute(
            "SELECT safe_detail_json FROM outage_reject_versions"
        ).fetchone()[0]
    assert run[0] == "completed"
    assert json.loads(reject_json) == {
        "error_message": "invalid local incident timestamp",
        "raw_row": {"HV_INCIDENT_TIME": "not-a-date"},
    }
    assert marker not in reject_json


@pytest.mark.parametrize(
    "invalid_case",
    [
        "duplicate_snapshot",
        "missing_snapshot",
        "extra_resource",
        "duplicate_attempt",
        "missing_attempt",
        "cross_run_attempt",
        "failed_attempt",
        "attempt_snapshot_mismatch",
        "attempt_hash_mismatch",
        "attempt_size_mismatch",
        "resources_seen_mismatch",
        "row_count_mismatch",
        "event_resource_mismatch",
        "duplicate_event",
        "duplicate_reject",
    ],
)
def test_commit_ingestion_run_rejects_malformed_exact_run_before_mutation(
    invalid_case: str,
    temp_db: Path,
    tmp_path: Path,
    source_snapshot: SourceSnapshot,
    parsed_event: OutageEvent,
) -> None:
    seed = _exact_run_payload(
        source_snapshot,
        parsed_event,
        run_id="run:valid-seed",
    )
    commit_ingestion_run(**seed, db_path=temp_db)
    with get_connection(temp_db) as connection:
        before_dump = "\n".join(connection.iterdump())
    before_current = current_outage_snapshot_ids(db_path=temp_db)

    invalid = _exact_run_payload(
        source_snapshot,
        parsed_event,
        run_id=f"run:invalid:{invalid_case}",
    )
    snapshots = invalid["snapshots"]
    attempts = invalid["fetch_attempts"]
    if invalid_case == "duplicate_snapshot":
        snapshots.append(snapshots[0])
    elif invalid_case == "missing_snapshot":
        snapshots.pop()
    elif invalid_case == "extra_resource":
        snapshots.append(
            snapshots[0].model_copy(
                update={
                    "snapshot_id": source_snapshot_id("extra", "c" * 64),
                    "source_resource_id": "extra",
                    "content_sha256": "c" * 64,
                }
            )
        )
    elif invalid_case == "duplicate_attempt":
        attempts.append(attempts[0])
    elif invalid_case == "missing_attempt":
        attempts.pop()
    elif invalid_case == "cross_run_attempt":
        attempts[0] = attempts[0].model_copy(update={"run_id": "run:other"})
    elif invalid_case == "failed_attempt":
        attempts[0] = attempts[0].model_copy(update={"status": "failed"})
    elif invalid_case == "attempt_snapshot_mismatch":
        attempts[0] = attempts[0].model_copy(
            update={"source_snapshot_id": snapshots[1].snapshot_id}
        )
    elif invalid_case == "attempt_hash_mismatch":
        attempts[0] = attempts[0].model_copy(update={"content_sha256": "d" * 64})
    elif invalid_case == "attempt_size_mismatch":
        attempts[0] = attempts[0].model_copy(update={"byte_size": 999})
    elif invalid_case == "resources_seen_mismatch":
        invalid["resources_seen"] = 3
    elif invalid_case == "row_count_mismatch":
        snapshots[0] = snapshots[0].model_copy(update={"row_count": 99})
    elif invalid_case == "event_resource_mismatch":
        invalid["events"][0] = invalid["events"][0].model_copy(
            update={"source_resource_id": SHEPD_RESOURCE_ID}
        )
    elif invalid_case == "duplicate_event":
        invalid["events"].append(invalid["events"][0])
        snapshots[0] = snapshots[0].model_copy(update={"row_count": 2})
    elif invalid_case == "duplicate_reject":
        reject = OutageReject(
            run_id=invalid["run_id"],
            source_resource_id=SEPD_RESOURCE_ID,
            row_number=2,
            error_code="invalid",
            error_message="invalid row",
            raw_row={"value": "bad"},
        )
        invalid["rejects"] = [reject, reject]
        snapshots[0] = snapshots[0].model_copy(update={"row_count": 3})

    fresh_db = tmp_path / f"invalid-{invalid_case}.sqlite3"
    with pytest.raises(ValueError, match="exact completed run"):
        commit_ingestion_run(**invalid, db_path=fresh_db)
    assert fresh_db.exists() is False

    with pytest.raises(ValueError, match="exact completed run"):
        commit_ingestion_run(**invalid, db_path=temp_db)
    with get_connection(temp_db) as connection:
        after_dump = "\n".join(connection.iterdump())
    assert after_dump == before_dump
    assert current_outage_snapshot_ids(db_path=temp_db) == before_current


def test_commit_ingestion_run_rolls_back_running_row_and_all_payloads(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
    parsed_event: OutageEvent,
) -> None:
    invalid = _exact_run_payload(
        source_snapshot,
        parsed_event,
        run_id="run:rollback",
    )
    invalid["events"][0] = invalid["events"][0].model_copy(
        update={"source_snapshot_id": "sha256:missing"}
    )

    with pytest.raises(ValueError, match="exact completed run"):
        commit_ingestion_run(**invalid, db_path=temp_db)

    assert temp_db.exists() is False


def test_failed_run_records_only_redacted_safe_failure_state(
    temp_db: Path,
) -> None:
    marker = "SYNTHETIC_SIGNATURE_MUST_NOT_PERSIST"

    result = record_failed_ingestion_run(
        run_id="run:failed",
        resources_seen=1,
        error=RuntimeError(
            "https://storage.invalid/file.csv?X-Amz-Signature=" + marker
        ),
        warnings=[{"signed_url": marker}, "safe warning"],
        db_path=temp_db,
    )

    assert result.status == "failed"
    with get_connection(temp_db) as connection:
        row = connection.execute(
            """SELECT status, error, warnings_json FROM ingestion_runs
               WHERE run_id = ?""",
            ("run:failed",),
        ).fetchone()
        payload = "\n".join(connection.iterdump())
    assert tuple(row[:2]) == ("failed", "RuntimeError: operation failed")
    assert json.loads(row[2]) == [{}, "safe warning"]
    assert marker not in payload
    assert "X-Amz-Signature" not in payload
    assert count_source_snapshots(db_path=temp_db) == 0
    with pytest.raises(ValueError, match="current atomic"):
        count_outage_events(db_path=temp_db)


def test_signed_r2_redirect_material_never_crosses_persistence_boundaries(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
    parsed_event: OutageEvent,
) -> None:
    host = "83025b28472d6aa2bf5ae59f3724aa78.r2.cloudflarestorage.com"
    path = (
        "/dx-sse-prod/resources/"
        "ab32515f-76f2-421d-8034-7d5b01325a33/synthetic.csv"
    )
    markers = {
        "X-Amz-Algorithm": "ALGORITHM_MARKER",
        "X-Amz-Date": "DATE_MARKER",
        "X-Amz-Expires": "EXPIRES_MARKER",
        "X-Amz-SignedHeaders": "SIGNED_HEADERS_MARKER",
        "X-Amz-Signature": "SIGNATURE_MARKER",
    }
    query = "&".join(f"{key}={value}" for key, value in markers.items())
    signed_url = f"https://{host}{path}?{query}"
    nested_payload = {
        "arbitrary": [
            signed_url,
            {"value": signed_url},
            {"X-Amz-Date": markers["X-Amz-Date"]},
        ]
    }
    reject = OutageReject(
        run_id="run:signed-completed",
        source_resource_id=source_snapshot.source_resource_id,
        row_number=2,
        error_code="download_failed",
        error_message=f"ordinary reject context: {signed_url}",
        raw_row={
            "ordinary_raw_value": "preserve reject evidence",
            "nested": nested_payload,
            "standalone_field": (
                f"X-Amz-Expires={markers['X-Amz-Expires']}"
            ),
        },
    )

    completed = _commit_exact_run(
        source_snapshot,
        parsed_event,
        run_id="run:signed-completed",
        db_path=temp_db,
        rejects=[reject],
        warnings=[
            "preserve ordinary completed warning",
            signed_url,
            nested_payload,
            f"prefix X-Amz-Algorithm={markers['X-Amz-Algorithm']} suffix",
        ],
    )
    failed = record_failed_ingestion_run(
        run_id="run:signed-failed",
        resources_seen=1,
        error=RuntimeError(signed_url),
        warnings=[
            "preserve ordinary failed warning",
            signed_url,
            nested_payload,
            f"X-Amz-SignedHeaders={markers['X-Amz-SignedHeaders']}",
        ],
        db_path=temp_db,
    )

    with get_connection(temp_db) as connection:
        sqlite_text = "\n".join(connection.iterdump())

    assert completed.warnings[0] == "preserve ordinary completed warning"
    assert failed.warnings[0] == "preserve ordinary failed warning"
    for forbidden in (
        signed_url,
        host,
        path,
        *markers,
        *markers.values(),
    ):
        assert forbidden not in sqlite_text
        assert forbidden not in json.dumps(completed.model_dump())
        assert forbidden not in json.dumps(failed.model_dump())
    assert "preserve ordinary completed warning" in sqlite_text
    assert "preserve ordinary failed warning" in sqlite_text
    assert "preserve reject evidence" in sqlite_text


def test_encoded_signed_redirect_material_never_crosses_persistence_boundaries(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
    parsed_event: OutageEvent,
) -> None:
    def encode_every_byte(value: str) -> str:
        return "".join(f"%{byte:02X}" for byte in value.encode())

    host = "83025b28472d6aa2bf5ae59f3724aa78.r2.cloudflarestorage.com"
    path = (
        "/dx-sse-prod/resources/"
        "ab32515f-76f2-421d-8034-7d5b01325a33/encoded.csv"
    )
    signed_url = (
        f"https://{host}{path}?"
        "X-Amz-Date=ENCODED_DATE_MARKER&"
        "X-Amz-Expires=ENCODED_EXPIRES_MARKER"
    )
    mixed_case_url = (
        f"hTtPs://{host.upper()}{path}?"
        "x-aMz-aLgOrItHm=MIXED_ALGORITHM_MARKER"
    )
    encoded_url = quote(signed_url, safe="")
    double_encoded_url = quote(encoded_url, safe="")
    encoded_mixed_url = quote(mixed_case_url, safe="")
    fully_encoded_url = encode_every_byte(signed_url)
    double_fully_encoded_url = quote(fully_encoded_url, safe="")
    encoded_pair = encode_every_byte(
        "X-Amz-Date=FULLY_ENCODED_VALUE_MARKER"
    )
    double_encoded_pair = quote(encoded_pair, safe="")
    encoded_payload = {
        "ordinary": "preserve encoded reject evidence",
        "signed%5Furl": encoded_url,
        "redirect%255Furl": double_encoded_url,
        "X%2DAmz%2DDate": "ENCODED_KEY_MARKER",
        "X%252DAmz%252DExpires": "DOUBLE_ENCODED_KEY_MARKER",
        "x%2DaMz%2DdAtE": encode_every_byte("MIXED_KEY_VALUE_MARKER"),
        "malformed_contamination": encoded_url + "%GG",
        "nested": [
            encoded_url,
            {"value": double_encoded_url},
            fully_encoded_url,
            double_fully_encoded_url,
            quote("X-Amz-Date=ENCODED_STRING_MARKER", safe=""),
            quote(
                quote(
                    "x-AmZ-SignedHeaders=DOUBLE_ENCODED_STRING_MARKER",
                    safe="",
                ),
                safe="",
            ),
            encoded_pair,
            double_encoded_pair,
        ],
    }
    reject = OutageReject(
        run_id="run:encoded-completed",
        source_resource_id=source_snapshot.source_resource_id,
        row_number=3,
        error_code="download_failed",
        error_message=(
            f"preserve encoded reject context: {double_encoded_url}"
        ),
        raw_row=encoded_payload,
    )

    completed = _commit_exact_run(
        source_snapshot,
        parsed_event,
        run_id="run:encoded-completed",
        db_path=temp_db,
        rejects=[reject],
        warnings=[
            "preserve ordinary encoded completed warning",
            encoded_url,
            double_encoded_url,
            encoded_mixed_url,
            fully_encoded_url,
            double_fully_encoded_url,
            encoded_payload,
        ],
    )
    failed = record_failed_ingestion_run(
        run_id="run:encoded-failed",
        resources_seen=1,
        error=RuntimeError(double_encoded_url),
        warnings=[
            "preserve ordinary encoded failed warning",
            encoded_url,
            double_encoded_url,
            encoded_mixed_url,
            fully_encoded_url,
            double_fully_encoded_url,
            encoded_payload,
        ],
        db_path=temp_db,
    )

    with get_connection(temp_db) as connection:
        sqlite_text = "\n".join(connection.iterdump())

    assert completed.warnings[0] == (
        "preserve ordinary encoded completed warning"
    )
    assert failed.warnings[0] == "preserve ordinary encoded failed warning"
    result_text = json.dumps(
        [completed.model_dump(), failed.model_dump()],
        sort_keys=True,
    )
    for forbidden in (
        host,
        host.upper(),
        path,
        signed_url,
        mixed_case_url,
        encoded_url,
        double_encoded_url,
        encoded_mixed_url,
        fully_encoded_url,
        double_fully_encoded_url,
        "X-Amz-Date",
        "X-Amz-Expires",
        "x-aMz-aLgOrItHm",
        "X%2DAmz%2DDate",
        "X%252DAmz%252DExpires",
        "signed%5Furl",
        "redirect%255Furl",
        encoded_pair,
        double_encoded_pair,
        "ENCODED_DATE_MARKER",
        "ENCODED_EXPIRES_MARKER",
        "MIXED_ALGORITHM_MARKER",
        "ENCODED_KEY_MARKER",
        "DOUBLE_ENCODED_KEY_MARKER",
        "ENCODED_STRING_MARKER",
        "DOUBLE_ENCODED_STRING_MARKER",
        "FULLY_ENCODED_VALUE_MARKER",
        "MIXED_KEY_VALUE_MARKER",
    ):
        assert forbidden not in sqlite_text
        assert forbidden not in result_text
    assert "preserve ordinary encoded completed warning" in sqlite_text
    assert "preserve ordinary encoded failed warning" in sqlite_text
    assert "preserve encoded reject evidence" in sqlite_text


def test_default_port_signed_redirect_never_crosses_persistence_boundaries(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
    parsed_event: OutageEvent,
) -> None:
    host = "83025b28472d6aa2bf5ae59f3724aa78.r2.cloudflarestorage.com"
    path = (
        "/dx-sse-prod/resources/"
        "ab32515f-76f2-421d-8034-7d5b01325a33/port.csv"
    )
    signed_url = (
        f"https://{host}:443{path}?"
        "X-Amz-Date=PORT_DATE_MARKER&X-Amz-Signature=PORT_SIGNATURE_MARKER"
    )
    encoded_url = quote(signed_url, safe="")
    double_encoded_url = quote(encoded_url, safe="")
    reject = OutageReject(
        run_id="run:port-completed",
        source_resource_id=source_snapshot.source_resource_id,
        row_number=4,
        error_code="download_failed",
        error_message=f"default-port redirect: {signed_url}",
        raw_row={
            "ordinary": "preserve default-port reject evidence",
            "nested": [signed_url, encoded_url, {"value": double_encoded_url}],
        },
    )

    completed = _commit_exact_run(
        source_snapshot,
        parsed_event,
        run_id="run:port-completed",
        db_path=temp_db,
        rejects=[reject],
        warnings=[
            "preserve ordinary default-port completed warning",
            signed_url,
            encoded_url,
            double_encoded_url,
        ],
    )
    failed = record_failed_ingestion_run(
        run_id="run:port-failed",
        resources_seen=1,
        error=RuntimeError(signed_url),
        warnings=[
            "preserve ordinary default-port failed warning",
            signed_url,
            encoded_url,
            double_encoded_url,
        ],
        db_path=temp_db,
    )

    with get_connection(temp_db) as connection:
        sqlite_text = "\n".join(connection.iterdump())
    result_text = json.dumps(
        [completed.model_dump(), failed.model_dump()],
        sort_keys=True,
    )

    for forbidden in (
        host,
        f"{host}:443",
        path,
        signed_url,
        encoded_url,
        double_encoded_url,
        "X-Amz-Date",
        "X-Amz-Signature",
        "PORT_DATE_MARKER",
        "PORT_SIGNATURE_MARKER",
    ):
        assert forbidden not in sqlite_text
        assert forbidden not in result_text
    assert "preserve ordinary default-port completed warning" in sqlite_text
    assert "preserve ordinary default-port failed warning" in sqlite_text
    assert "preserve default-port reject evidence" in sqlite_text


def test_benign_percent_and_multiline_warnings_survive_persistence(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
    parsed_event: OutageEvent,
) -> None:
    benign = [
        "coverage is 95% complete",
        "encoded coverage is 95%25 complete",
        "malformed public label %GG",
        "ordinary first line\nordinary second line",
    ]

    completed = _commit_exact_run(
        source_snapshot,
        parsed_event,
        run_id="run:benign-completed",
        db_path=temp_db,
        warnings=benign,
    )
    failed = record_failed_ingestion_run(
        run_id="run:benign-failed",
        resources_seen=1,
        error=RuntimeError("ordinary public failure"),
        warnings=benign,
        db_path=temp_db,
    )

    with get_connection(temp_db) as connection:
        persisted = {
            row["run_id"]: json.loads(row["warnings_json"])
            for row in connection.execute(
                """SELECT run_id, warnings_json FROM ingestion_runs
                   ORDER BY run_id"""
            )
        }

    assert completed.warnings == benign
    assert failed.warnings == benign
    assert persisted == {
        "run:benign-completed": benign,
        "run:benign-failed": benign,
    }


def fully_byte_encoded(value: str, depth: int) -> str:
    if depth == 0:
        return value
    value = "".join(f"%{byte:02X}" for byte in value.encode("utf-8"))
    for _ in range(1, depth):
        value = quote(value, safe="")
    return value


def synthetic_signed_target(marker: str) -> str:
    return (
        "https://83025b28472d6aa2bf5ae59f3724aa78."
        "r2.cloudflarestorage.com/x?X-Amz-Signature=" + marker
    )


@pytest.mark.parametrize("depth", [0, 1, 4, 8])
def test_signed_detector_covers_permitted_decode_budget(depth: int) -> None:
    value = fully_byte_encoded(
        synthetic_signed_target("SYNTHETIC_DEPTH_MARKER"),
        depth,
    )

    assert sanitise_diagnostic_value(value) == UNSAFE_VALUE_SENTINEL


def test_ninth_decoding_layer_fails_closed() -> None:
    value = fully_byte_encoded(
        synthetic_signed_target("SYNTHETIC_NINTH_MARKER"),
        9,
    )

    assert sanitise_diagnostic_value(value) == UNSAFE_VALUE_SENTINEL


@pytest.mark.parametrize(
    "value",
    ["95%", "95%25", "%GG", "line one\nline two"],
)
def test_benign_percent_and_multiline_values_round_trip(value: str) -> None:
    assert sanitise_diagnostic_value(value) == value


@pytest.mark.parametrize("depth", [1, 4, 8, 9])
def test_fully_byte_encoded_mapping_keys_fail_closed_at_every_depth(
    depth: int,
) -> None:
    marker = "SYNTHETIC_ENCODED_KEY_MARKER"
    unsafe_key = fully_byte_encoded("signed_url", depth)
    value = {unsafe_key: marker, "ordinary": "retained"}

    sanitised = sanitise_diagnostic_value(value)
    rendered = json.dumps(sanitised, sort_keys=True)

    assert marker not in rendered
    assert unsafe_key not in rendered
    with pytest.raises(UnsafePersistenceValueError):
        require_exact_safe_structure(value)


def test_direct_parser_rejects_unsafe_raw_record_without_reflection(
    sample_row: dict[str, str],
) -> None:
    marker = "SYNTHETIC_DIRECT_PARSER_MARKER"
    target = synthetic_signed_target(marker)

    with pytest.raises(UnsafePersistenceValueError) as caught:
        parse_sepd(sample_row | {"CAUSE": target})

    exception_state = repr(caught.value.__dict__)
    for forbidden in (marker, target):
        assert forbidden not in str(caught.value)
        assert forbidden not in repr(caught.value)
        assert forbidden not in exception_state


def test_extra_column_unsafe_value_is_sanitised_and_later_row_continues(
    sepd_csv_bytes: bytes,
) -> None:
    marker = "SYNTHETIC_EXTRA_COLUMN_MARKER"
    target = synthetic_signed_target(marker)
    rows = list(csv.reader(io.StringIO(sepd_csv_bytes.decode())))
    csv_text = io.StringIO(newline="")
    csv.writer(csv_text, lineterminator="\n").writerows(
        [rows[0], [*rows[1], target], rows[2]]
    )

    results = list(
        iter_ssen_hv_csv(csv_text.getvalue().encode(), licence_area="SEPD")
    )

    assert len(results) == 2
    assert isinstance(results[0], OutageRowError)
    assert results[0].code == "invalid_row_shape"
    error_state = repr(results[0].__dict__)
    for forbidden in (marker, target):
        assert forbidden not in str(results[0])
        assert forbidden not in repr(results[0])
        assert forbidden not in error_state
    assert isinstance(results[1], OutageEvent)
    assert results[1].raw_record == dict(zip(SEPD_COLUMNS, rows[2], strict=True))


def test_malformed_unsafe_row_is_safe_and_later_row_continues(
    sepd_csv_bytes: bytes,
) -> None:
    marker = "SYNTHETIC_MALFORMED_ROW_MARKER"
    target = synthetic_signed_target(marker)
    lines = sepd_csv_bytes.decode().splitlines()
    malformed = lines[1].replace("Switchgear", f'"bad"tail{target}', 1)
    csv_bytes = "\n".join((lines[0], malformed, lines[2])).encode()

    results = list(iter_ssen_hv_csv(csv_bytes, licence_area="SEPD"))

    assert len(results) == 2
    assert isinstance(results[0], OutageRowError)
    assert results[0].code == "invalid_row_shape"
    error_state = repr(results[0].__dict__)
    for forbidden in (marker, target):
        assert forbidden not in str(results[0])
        assert forbidden not in repr(results[0])
        assert forbidden not in error_state
    assert isinstance(results[1], OutageEvent)


def test_persistence_rejects_structured_value_over_512_kib() -> None:
    chunk = "x" * (MAX_PERSISTED_STRING_BYTES - 128)
    value = [chunk for _ in range(9)]

    assert len(json.dumps(value).encode()) > MAX_STRUCTURED_VALUE_BYTES
    assert sanitise_diagnostic_value(value) == UNSAFE_VALUE_SENTINEL
    with pytest.raises(UnsafePersistenceValueError):
        require_exact_safe_structure(value)


@pytest.mark.parametrize(
    "nested",
    [
        {"evidence": [synthetic_signed_target("SYNTHETIC_NESTED_MARKER")]},
        {"evidence": ["x" * (MAX_PERSISTED_STRING_BYTES + 1)]},
    ],
)
def test_exact_safe_structure_rejects_signed_or_oversize_nested_evidence(
    nested: dict[str, Any],
) -> None:
    with pytest.raises(UnsafePersistenceValueError) as caught:
        require_exact_safe_structure(nested)

    assert "SYNTHETIC_" not in str(caught.value)


def test_persistence_rejects_oversize_mapping_key() -> None:
    value = {"k" * (MAX_PERSISTED_STRING_BYTES + 1): "ordinary"}

    assert sanitise_diagnostic_value(value) == UNSAFE_VALUE_SENTINEL
    with pytest.raises(UnsafePersistenceValueError):
        require_exact_safe_structure(value)


def test_persistence_rejects_depth_over_32_and_items_over_10000() -> None:
    too_deep: Any = "leaf"
    for _ in range(MAX_CONTAINER_DEPTH + 1):
        too_deep = [too_deep]
    too_many = list(range(MAX_CONTAINER_ITEMS + 1))

    for value in (too_deep, too_many):
        assert sanitise_diagnostic_value(value) == UNSAFE_VALUE_SENTINEL
        with pytest.raises(UnsafePersistenceValueError):
            require_exact_safe_structure(value)


def test_persistence_rejects_cycles_and_non_json_values() -> None:
    cyclic: list[Any] = []
    cyclic.append(cyclic)

    for value in (cyclic, {"value": object()}):
        assert sanitise_diagnostic_value(value) == UNSAFE_VALUE_SENTINEL
        with pytest.raises(UnsafePersistenceValueError):
            require_exact_safe_structure(value)


def test_exact_string_and_mapping_key_byte_limits_accept_boundary_only() -> None:
    accepted_leaf = "é" * 32_768
    rejected_leaf = accepted_leaf + "x"
    accepted_key = "k" * 65_536
    rejected_key = accepted_key + "k"

    assert len(accepted_leaf.encode("utf-8")) == 65_536
    assert len(rejected_leaf.encode("utf-8")) == 65_537
    assert sanitise_diagnostic_value(accepted_leaf) == accepted_leaf
    assert sanitise_diagnostic_value(rejected_leaf) == UNSAFE_VALUE_SENTINEL
    assert sanitise_diagnostic_value({accepted_key: "v"}) == {accepted_key: "v"}
    assert sanitise_diagnostic_value({rejected_key: "v"}) == UNSAFE_VALUE_SENTINEL
    require_exact_safe_structure(accepted_leaf)
    require_exact_safe_structure({accepted_key: "v"})
    with pytest.raises(UnsafePersistenceValueError):
        require_exact_safe_structure(rejected_leaf)
    with pytest.raises(UnsafePersistenceValueError):
        require_exact_safe_structure({rejected_key: "v"})


def test_exact_structured_byte_limit_accepts_boundary_only() -> None:
    accepted = ["x" * 65_536 for _ in range(7)] + ["x" * 65_511]
    rejected = [*accepted[:-1], accepted[-1] + "x"]

    def canonical_size(value: Any) -> int:
        return len(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )

    assert canonical_size(accepted) == 524_288
    assert canonical_size(rejected) == 524_289
    assert sanitise_diagnostic_value(accepted) == accepted
    assert sanitise_diagnostic_value(rejected) == UNSAFE_VALUE_SENTINEL
    require_exact_safe_structure(accepted)
    with pytest.raises(UnsafePersistenceValueError):
        require_exact_safe_structure(rejected)


def test_exact_depth_and_item_limits_accept_boundary_only() -> None:
    accepted_depth: Any = "leaf"
    for _ in range(32):
        accepted_depth = [accepted_depth]
    rejected_depth = [accepted_depth]
    accepted_items = list(range(10_000))
    rejected_items = list(range(10_001))

    assert sanitise_diagnostic_value(accepted_depth) == accepted_depth
    assert sanitise_diagnostic_value(rejected_depth) == UNSAFE_VALUE_SENTINEL
    assert sanitise_diagnostic_value(accepted_items) == accepted_items
    assert sanitise_diagnostic_value(rejected_items) == UNSAFE_VALUE_SENTINEL
    require_exact_safe_structure(accepted_depth)
    require_exact_safe_structure(accepted_items)
    with pytest.raises(UnsafePersistenceValueError):
        require_exact_safe_structure(rejected_depth)
    with pytest.raises(UnsafePersistenceValueError):
        require_exact_safe_structure(rejected_items)


def test_event_raw_record_is_never_sanitised(
    temp_db: Path,
    parsed_event: OutageEvent,
) -> None:
    unsafe = parsed_event.model_copy(
        update={"raw_record": {"note": "x" * (MAX_PERSISTED_STRING_BYTES + 1)}}
    )

    with pytest.raises(UnsafePersistenceValueError):
        upsert_outage_events([unsafe], db_path=temp_db)

    with get_connection(temp_db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM outage_events").fetchone()[0] == 0


def test_unsafe_event_raw_record_becomes_stable_row_reject(
    sample_row: dict[str, str],
) -> None:
    marker = "SYNTHETIC_ROW_REJECT_MARKER"
    unsafe_row = sample_row | {"CAUSE": synthetic_signed_target(marker)}
    rows = [SEPD_COLUMNS, tuple(unsafe_row[key] for key in SEPD_COLUMNS)]
    csv_text = io.StringIO(newline="")
    csv.writer(csv_text, lineterminator="\n").writerows(rows)

    results = list(iter_ssen_hv_csv(csv_text.getvalue().encode(), licence_area="SEPD"))

    assert len(results) == 1
    assert isinstance(results[0], OutageRowError)
    assert results[0].code == "unsafe_raw_record"
    assert results[0].message == "raw outage row is unsafe for persistence"
    assert marker not in json.dumps(results[0].raw_record, sort_keys=True)


def test_mixed_safe_and_unsafe_rows_complete_with_one_reject(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
    sample_row: dict[str, str],
) -> None:
    marker = "SYNTHETIC_MIXED_ROW_MARKER"
    unsafe_row = sample_row | {
        "CAUSE": fully_byte_encoded(synthetic_signed_target(marker), 4)
    }
    safe_row = sample_row | {
        "DIST_HV_REF": "SYNTHETIC-SAFE-ROW",
        "NRN_SOUTH": "SYNTHETIC-SAFE-NETWORK",
    }
    csv_text = io.StringIO(newline="")
    csv.writer(csv_text, lineterminator="\n").writerows(
        [
            SEPD_COLUMNS,
            [unsafe_row[key] for key in SEPD_COLUMNS],
            [safe_row[key] for key in SEPD_COLUMNS],
        ]
    )

    parsed = list(
        iter_ssen_hv_csv(
            csv_text.getvalue().encode(),
            licence_area="SEPD",
            source_resource_id=source_snapshot.source_resource_id,
            snapshot_id=source_snapshot.snapshot_id,
        )
    )
    assert isinstance(parsed[0], OutageRowError)
    assert isinstance(parsed[1], OutageEvent)
    reject = OutageReject(
        run_id="run:mixed-boundary",
        source_resource_id=source_snapshot.source_resource_id,
        row_number=parsed[0].row_number or 2,
        error_code=parsed[0].code,
        error_message=parsed[0].message,
        raw_row=parsed[0].raw_record,
    )

    result = _commit_exact_run(
        source_snapshot,
        parsed[1],
        run_id="run:mixed-boundary",
        db_path=temp_db,
        rejects=[reject],
    )

    with get_connection(temp_db) as connection:
        sqlite_text = "\n".join(connection.iterdump())
    assert (result.events_written, result.rejects_written) == (1, 1)
    assert marker not in sqlite_text
    assert parsed[1].raw_record == safe_row


def test_budget_failures_leave_no_partial_run_state(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
    parsed_event: OutageEvent,
) -> None:
    unsafe = parsed_event.model_copy(
        update={"raw_record": {"note": "x" * (MAX_PERSISTED_STRING_BYTES + 1)}}
    )

    payload = _exact_run_payload(
        source_snapshot,
        parsed_event,
        run_id="run:unsafe-budget",
    )
    payload["events"] = [
        unsafe.model_copy(
            update={
                "source_snapshot_id": payload["snapshots"][0].snapshot_id,
                "source_resource_id": SEPD_RESOURCE_ID,
            }
        )
    ]

    with pytest.raises(UnsafePersistenceValueError):
        commit_ingestion_run(**payload, db_path=temp_db)

    with get_connection(temp_db) as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "source_snapshots",
                "ingestion_runs",
                "outage_events",
                "outage_rejects",
            )
        }
    assert counts == {table: 0 for table in counts}


@pytest.mark.parametrize("depth", [8, 9])
def test_deep_completed_failed_reject_and_results_share_the_same_boundary(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
    parsed_event: OutageEvent,
    depth: int,
) -> None:
    marker = f"SYNTHETIC_SHARED_BOUNDARY_MARKER_{depth}"
    target = synthetic_signed_target(marker)
    unsafe = fully_byte_encoded(target, depth)
    unsafe_key = fully_byte_encoded("signed_url", depth)
    run_suffix = str(depth)
    reject = OutageReject(
        run_id=f"run:shared-completed:{run_suffix}",
        source_resource_id=source_snapshot.source_resource_id,
        row_number=2,
        error_code="unsafe_raw_record",
        error_message=unsafe,
        raw_row={unsafe_key: unsafe, "value": unsafe},
    )

    completed = _commit_exact_run(
        source_snapshot,
        parsed_event,
        run_id=f"run:shared-completed:{run_suffix}",
        db_path=temp_db,
        rejects=[reject],
        warnings=[{unsafe_key: unsafe, "value": unsafe}],
    )
    failed = record_failed_ingestion_run(
        run_id=f"run:shared-failed:{run_suffix}",
        resources_seen=1,
        error=RuntimeError(unsafe),
        warnings=[{unsafe_key: unsafe, "value": unsafe}],
        db_path=temp_db,
    )

    with get_connection(temp_db) as connection:
        sqlite_text = "\n".join(connection.iterdump())
    returned = json.dumps(
        [completed.model_dump(), failed.model_dump()],
        sort_keys=True,
    )
    for forbidden in (marker, target, unsafe, unsafe_key):
        assert forbidden not in sqlite_text
        assert forbidden not in returned
    assert UNSAFE_VALUE_SENTINEL in sqlite_text
    assert UNSAFE_VALUE_SENTINEL in returned


def test_exact_safe_raw_record_round_trips_without_mutation(
    sample_row: dict[str, str],
) -> None:
    before = dict(sample_row)

    assert require_exact_safe_raw_record(sample_row) is None
    assert sample_row == before


def ssen_resource(licence_area: LicenceArea) -> SourceResource:
    resource_id = SEPD_RESOURCE_ID if licence_area == "SEPD" else SHEPD_RESOURCE_ID
    name = f"NaFIRS HV Faults {licence_area} (CSV)"
    url = (
        "https://data-api.ssen.co.uk/dataset/"
        "b0a58349-2ce6-4fa8-9238-a5564f966433/resource/"
        f"{resource_id}/download/20260728_nafirs_hv_{licence_area.lower()}_csv.csv"
    )
    return SourceResource(
        source_dataset_id="nafirs-hv-faults",
        package_id="b0a58349-2ce6-4fa8-9238-a5564f966433",
        source_resource_id=resource_id,
        licence_area=licence_area,
        name=name,
        stable_url=url,
        source_modified_at=datetime(2026, 7, 28, 6, 7, tzinfo=timezone.utc),
        format="CSV",
        media_type="text/csv",
        datastore_active=True,
        raw_record={
            "id": resource_id,
            "name": name,
            "url": url,
            "format": "CSV",
            "mimetype": "text/csv",
            "datastore_active": True,
        },
    )


class TimedByteStream(httpx.SyncByteStream):
    def __init__(
        self,
        chunks: list[bytes],
        *,
        tick: Any | None = None,
    ) -> None:
        self.chunks = chunks
        self.tick = tick

    def __iter__(self) -> Any:
        for chunk in self.chunks:
            if self.tick is not None:
                self.tick()
            yield chunk


class ScriptedSocket:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def settimeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)


class ScriptedHTTPResponse:
    def __init__(
        self,
        status: int,
        *,
        headers: dict[str, str] | None = None,
        chunks: list[bytes] | None = None,
        on_read: Any | None = None,
    ) -> None:
        self.status = status
        self._headers = {key.lower(): value for key, value in (headers or {}).items()}
        self._chunks = list(chunks or [])
        self._on_read = on_read
        self.closed = False

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self._headers.get(name.lower(), default)

    def read(self, amount: int) -> bytes:
        del amount
        if self._on_read is not None:
            self._on_read()
        return self._chunks.pop(0) if self._chunks else b""

    def close(self) -> None:
        self.closed = True


class ScriptedHTTPSConnection:
    def __init__(self, response: ScriptedHTTPResponse | BaseException) -> None:
        self.response = response
        self.sock = ScriptedSocket()
        self.connected = False
        self.closed = False
        self.requests: list[tuple[str, str]] = []

    def connect(self) -> None:
        self.connected = True

    def request(
        self,
        method: str,
        target: str,
        *,
        headers: dict[str, str],
    ) -> None:
        del headers
        self.requests.append((method, target))

    def getresponse(self) -> ScriptedHTTPResponse:
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response

    def close(self) -> None:
        self.closed = True


class ScriptedConnectionFactory:
    def __init__(
        self, responses: list[ScriptedHTTPResponse | BaseException]
    ) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, int, float]] = []
        self.connections: list[ScriptedHTTPSConnection] = []

    def __call__(
        self,
        host: str,
        port: int,
        timeout: float,
    ) -> ScriptedHTTPSConnection:
        self.calls.append((host, port, timeout))
        connection = ScriptedHTTPSConnection(self._responses.pop(0))
        self.connections.append(connection)
        return connection


def response_client(
    responses: list[httpx.Response],
    requests: list[httpx.Request] | None = None,
) -> httpx.Client:
    queued = list(responses)
    captured = requests if requests is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if not queued:
            raise AssertionError("unexpected request")
        return queued.pop(0)

    return httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    )


class ScriptedDeadlineTransport:
    def __init__(
        self,
        payloads: dict[str, bytes],
        *,
        fail_resource_id: str | None = None,
        token: str = "secret",
        on_download: Any | None = None,
    ) -> None:
        self.payloads = payloads
        self.fail_resource_id = fail_resource_id
        self._transient_token = token
        self.on_download = on_download
        self.requests: list[tuple[str, float]] = []
        self.closed = False

    def download(self, resource: SourceResource, *, deadline: float) -> bytes:
        self.requests.append((resource.source_resource_id, deadline))
        if self.on_download is not None:
            self.on_download(deadline)
        if resource.source_resource_id == self.fail_resource_id:
            raise SourceContractError(
                "SSEN resource did not return the required redirect",
                response_status=503,
                error_code="unexpected_initial_status",
            )
        return self.payloads[resource.source_resource_id]

    def close(self) -> None:
        self._transient_token = ""
        self.closed = True

    def __enter__(self) -> ScriptedDeadlineTransport:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def redirect_for(resource_id: str, token: str = "secret") -> httpx.Response:
    return httpx.Response(
        302,
        headers={
            "location": (
                "https://83025b28472d6aa2bf5ae59f3724aa78."
                "r2.cloudflarestorage.com/dx-sse-prod/resources/"
                f"{resource_id}/sample.csv?X-Amz-Signature={token}"
            )
        },
    )


def csv_response(content: bytes, **headers: str) -> httpx.Response:
    return httpx.Response(
        200,
        content=content,
        headers={"content-type": "text/csv", **headers},
    )


def sync_transport(
    sepd: bytes,
    shepd: bytes,
    *,
    token: str = "secret",
    fail_resource_id: str | None = None,
) -> ScriptedDeadlineTransport:
    payloads = {SEPD_RESOURCE_ID: sepd, SHEPD_RESOURCE_ID: shepd}
    return ScriptedDeadlineTransport(
        payloads,
        token=token,
        fail_resource_id=fail_resource_id,
    )


sync_client = sync_transport


def first_csv_row_only(content: bytes) -> bytes:
    rows = content.decode().splitlines()
    return ("\n".join(rows[:2]) + "\n").encode()


def csv_with_invalid_first_row(content: bytes) -> bytes:
    rows = content.decode().splitlines()
    values = rows[1].split(",")
    values[1] = "not-a-year"
    rows[1] = ",".join(values)
    return ("\n".join(rows) + "\n").encode()


def _active_child_pids() -> set[int]:
    return {
        child.pid
        for child in multiprocessing.active_children()
        if child.pid is not None
    }


def _scripted_redirect(location: str) -> ScriptedHTTPResponse:
    return ScriptedHTTPResponse(302, headers={"location": location})


def test_child_https_download_uses_exact_targets_and_emits_no_signed_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    literal_marker = "LITERAL_SIGNED_MARKER"
    encoded_marker = "ENCODED%5FSIGNED%5FMARKER"
    location = (
        "https://83025b28472d6aa2bf5ae59f3724aa78."
        "r2.cloudflarestorage.com/dx-sse-prod/resources/"
        f"{SEPD_RESOURCE_ID}/sample.csv?"
        f"X-Amz-Signature={literal_marker}&X-Amz-Credential={encoded_marker}"
    )
    final = ScriptedHTTPResponse(
        200,
        headers={"content-type": "text/csv"},
        chunks=[b"A,B\n", b"1,2\n"],
    )
    first = _scripted_redirect(location)
    factory = ScriptedConnectionFactory([first, final])
    for logger_name in ("app.outage_source", "httpx", "httpcore"):
        caplog.set_level(logging.DEBUG, logger=logger_name)

    content = _download_resource_in_child(
        ssen_resource("SEPD").model_dump(mode="python"),
        time.monotonic() + 180,
        connection_factory=factory,
    )

    assert content == b"A,B\n1,2\n"
    assert factory.connections[0].requests == [
        (
            "GET",
            "/dataset/b0a58349-2ce6-4fa8-9238-a5564f966433/resource/"
            f"{SEPD_RESOURCE_ID}/download/20260728_nafirs_hv_sepd_csv.csv",
        )
    ]
    assert factory.connections[1].requests == [
        ("GET", location.split("r2.cloudflarestorage.com", 1)[1])
    ]
    assert all(connection.connected and connection.closed for connection in factory.connections)
    assert first.closed is True
    assert final.closed is True
    assert literal_marker not in caplog.text
    assert encoded_marker not in caplog.text
    assert "X-Amz" not in caplog.text


def test_child_https_failure_emits_no_literal_or_encoded_signed_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    literal_marker = "LITERAL_FAILURE_MARKER"
    encoded_marker = "ENCODED%5FFAILURE%5FMARKER"
    location = (
        "https://83025b28472d6aa2bf5ae59f3724aa78."
        "r2.cloudflarestorage.com/dx-sse-prod/resources/"
        f"{SEPD_RESOURCE_ID}/sample.csv?"
        f"X-Amz-Signature={literal_marker}&X-Amz-Credential={encoded_marker}"
    )
    failure = RuntimeError(
        f"transport failed for {location}"
    )
    factory = ScriptedConnectionFactory(
        [_scripted_redirect(location), failure]
    )
    for logger_name in ("app.outage_source", "httpx", "httpcore"):
        caplog.set_level(logging.DEBUG, logger=logger_name)

    with pytest.raises(SourceContractError) as caught:
        _download_resource_in_child(
            ssen_resource("SEPD").model_dump(mode="python"),
            time.monotonic() + 180,
            connection_factory=factory,
        )

    surfaces = str(caught.value) + caplog.text
    assert literal_marker not in surfaces
    assert encoded_marker not in surfaces
    assert "X-Amz" not in surfaces
    assert all(connection.closed for connection in factory.connections)


def test_production_child_worker_uses_bounded_safe_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location = (
        "https://83025b28472d6aa2bf5ae59f3724aa78."
        "r2.cloudflarestorage.com/dx-sse-prod/resources/"
        f"{SEPD_RESOURCE_ID}/sample.csv?X-Amz-Signature=secret"
    )
    factory = ScriptedConnectionFactory(
        [
            _scripted_redirect(location),
            ScriptedHTTPResponse(
                200,
                headers={"content-type": "text/csv"},
                chunks=[b"csv"],
            ),
        ]
    )
    monkeypatch.setattr(
        "app.outage_source._create_https_connection",
        factory,
    )
    receive_connection, send_connection = multiprocessing.Pipe(duplex=False)
    try:
        _ssen_download_process_worker(
            send_connection,
            ssen_resource("SEPD").model_dump(mode="python"),
            time.monotonic() + 180,
        )
        assert receive_connection.recv_bytes(16) == b"Ocsv"
    finally:
        receive_connection.close()
        send_connection.close()


@pytest.mark.parametrize(
    "filename",
    [
        ".",
        "..",
        "../escape.csv",
        r"..\escape.csv",
        "%2e%2e",
        "%2E%2E",
        "%252e%252e",
        "%2fescape.csv",
        "%252Fescape.csv",
        "%5cescape.csv",
        "%255Cescape.csv",
        "%00.csv",
        "%2500.csv",
        "%",
        "%2",
        "%GG.csv",
        "%c0%af.csv",
    ],
)
def test_child_https_download_rejects_noncanonical_redirect_filename(
    filename: str,
) -> None:
    location = (
        "https://83025b28472d6aa2bf5ae59f3724aa78."
        "r2.cloudflarestorage.com/dx-sse-prod/resources/"
        f"{SEPD_RESOURCE_ID}/{filename}?X-Amz-Signature=secret"
    )
    first = _scripted_redirect(location)
    factory = ScriptedConnectionFactory([first])

    with pytest.raises(SourceContractError, match="unapproved redirect"):
        _download_resource_in_child(
            ssen_resource("SEPD").model_dump(mode="python"),
            time.monotonic() + 180,
            connection_factory=factory,
        )

    assert len(factory.connections) == 1
    assert first.closed is True
    assert factory.connections[0].closed is True


def test_child_https_download_clamps_connect_header_and_each_body_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": 0.0}
    monkeypatch.setattr("app.outage_source.time.monotonic", lambda: clock["now"])
    location = (
        "https://83025b28472d6aa2bf5ae59f3724aa78."
        "r2.cloudflarestorage.com/dx-sse-prod/resources/"
        f"{SEPD_RESOURCE_ID}/sample.csv?X-Amz-Signature=secret"
    )
    final = ScriptedHTTPResponse(
        200,
        headers={"content-type": "text/csv"},
        chunks=[b"a", b"b"],
        on_read=lambda: clock.update(now=175.0),
    )
    factory = ScriptedConnectionFactory(
        [_scripted_redirect(location), final]
    )

    assert _download_resource_in_child(
        ssen_resource("SEPD").model_dump(mode="python"),
        180.0,
        connection_factory=factory,
    ) == b"ab"

    assert [call[2] for call in factory.calls] == [10, 10]
    assert factory.connections[0].sock.timeouts[0] == 60
    assert factory.connections[1].sock.timeouts[0] == 60
    assert factory.connections[1].sock.timeouts[-1] == 5


def test_owned_process_transport_success_closes_every_process_and_pipe() -> None:
    before = _active_child_pids()
    transport = OwnedProcessSsenTransport(worker_target=_spawn_success_worker)

    for _ in range(3):
        assert transport.download(
            ssen_resource("SEPD"), deadline=time.monotonic() + 5
        ) == b"csv"

    assert _active_child_pids() == before


def test_owned_process_transport_failure_is_fixed_and_does_not_trace_request(
    capfd: pytest.CaptureFixture[str],
) -> None:
    marker = "SYNTHETIC_CHILD_FAILURE_MUST_NOT_LEAK"
    before = _active_child_pids()
    transport = OwnedProcessSsenTransport(
        worker_target=_spawn_marker_failure_worker
    )

    with pytest.raises(SourceContractError) as caught:
        transport.download(
            ssen_resource("SEPD"), deadline=time.monotonic() + 5
        )

    captured = capfd.readouterr()
    surfaces = str(caught.value) + captured.out + captured.err
    assert marker not in surfaces
    assert "X-Amz-Signature" not in surfaces
    assert _active_child_pids() == before


@pytest.mark.parametrize("blocked_operation", ["header", "body"])
def test_owned_process_transport_terminates_non_cooperative_io_at_deadline(
    blocked_operation: str,
) -> None:
    del blocked_operation
    before = _active_child_pids()
    transport = OwnedProcessSsenTransport(
        worker_target=_spawn_non_cooperative_worker,
        poll_interval_seconds=0.005,
    )
    started = time.monotonic()

    with pytest.raises(SourceContractError, match="deadline"):
        transport.download(
            ssen_resource("SEPD"), deadline=started + 0.5
        )

    assert time.monotonic() - started < 2
    assert _active_child_pids() == before


@pytest.mark.parametrize(
    "worker_target",
    [_spawn_malformed_worker, _spawn_duplicate_worker, _spawn_oversize_worker],
)
def test_owned_process_transport_rejects_malformed_duplicate_and_oversize_ipc(
    worker_target: Any,
) -> None:
    before = _active_child_pids()
    transport = OwnedProcessSsenTransport(
        worker_target=worker_target,
        max_response_bytes=8,
    )

    with pytest.raises(SourceContractError, match="protocol"):
        transport.download(
            ssen_resource("SEPD"), deadline=time.monotonic() + 5
        )

    assert _active_child_pids() == before


def test_download_delegates_one_resource_with_one_absolute_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": 10.0}
    monkeypatch.setattr("app.outage_source.time.monotonic", lambda: clock["now"])
    transport = ScriptedDeadlineTransport({SEPD_RESOURCE_ID: b"A,B\n1,2\n"})

    assert download_ssen_hv_resource(
        transport, ssen_resource("SEPD")
    ) == b"A,B\n1,2\n"
    assert transport.requests == [(SEPD_RESOURCE_ID, 190.0)]


@pytest.mark.parametrize(
    "location",
    [
        "http://83025b28472d6aa2bf5ae59f3724aa78.r2.cloudflarestorage.com/x",
        "https://127.0.0.1/x",
        "https://example.test/x",
        "/relative",
    ],
)
def test_download_rejects_unapproved_redirects(location: str) -> None:
    first = _scripted_redirect(location)
    factory = ScriptedConnectionFactory([first])

    with pytest.raises(SourceContractError):
        _download_resource_in_child(
            ssen_resource("SEPD").model_dump(mode="python"),
            time.monotonic() + 180,
            connection_factory=factory,
        )

    assert first.closed is True
    assert factory.connections[0].closed is True


def test_download_rejects_second_redirect_without_following() -> None:
    location = redirect_for(SEPD_RESOURCE_ID).headers["location"]
    factory = ScriptedConnectionFactory(
        [_scripted_redirect(location), _scripted_redirect(location)]
    )

    with pytest.raises(SourceContractError, match="did not return 200"):
        _download_resource_in_child(
            ssen_resource("SEPD").model_dump(mode="python"),
            time.monotonic() + 180,
            connection_factory=factory,
        )

    assert len(factory.connections) == 2
    assert all(connection.closed for connection in factory.connections)


@pytest.mark.parametrize(
    ("size", "accepted"),
    [(7, True), (8, True), (9, False)],
)
def test_download_stream_size_boundaries_at_limit_minus_one_limit_and_plus_one(
    monkeypatch: pytest.MonkeyPatch,
    size: int,
    accepted: bool,
) -> None:
    monkeypatch.setattr("app.outage_source.SOURCE_MAX_RESPONSE_BYTES", 8)
    location = redirect_for(SEPD_RESOURCE_ID).headers["location"]
    factory = ScriptedConnectionFactory(
        [
            _scripted_redirect(location),
            ScriptedHTTPResponse(
                200,
                headers={"content-type": "text/csv"},
                chunks=[b"x" * size],
            ),
        ]
    )
    if accepted:
        assert len(_download_resource_in_child(
            ssen_resource("SEPD").model_dump(mode="python"),
            time.monotonic() + 180,
            connection_factory=factory,
        )) == size
    else:
        with pytest.raises(SourceContractError, match="size limit"):
            _download_resource_in_child(
                ssen_resource("SEPD").model_dump(mode="python"),
                time.monotonic() + 180,
                connection_factory=factory,
            )


def test_download_rejects_oversize_content_length_before_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.outage_source.SOURCE_MAX_RESPONSE_BYTES", 8)
    location = redirect_for(SEPD_RESOURCE_ID).headers["location"]
    final = ScriptedHTTPResponse(
        200,
        headers={"content-type": "text/csv", "content-length": "9"},
        chunks=[b"must-not-be-read"],
    )
    factory = ScriptedConnectionFactory([_scripted_redirect(location), final])

    with pytest.raises(SourceContractError, match="size limit"):
        _download_resource_in_child(
            ssen_resource("SEPD").model_dump(mode="python"),
            time.monotonic() + 180,
            connection_factory=factory,
        )

    assert final._chunks == [b"must-not-be-read"]


@pytest.mark.parametrize(
    ("elapsed", "accepted"),
    [(179.999, True), (180.0, False), (180.001, False)],
)
def test_download_enforces_total_deadline_across_redirects_and_slow_chunks(
    monkeypatch: pytest.MonkeyPatch,
    elapsed: float,
    accepted: bool,
) -> None:
    clock = {"now": 0.0}
    monkeypatch.setattr("app.outage_source.time.monotonic", lambda: clock["now"])
    def advance_and_enforce(deadline: float) -> None:
        clock["now"] = elapsed
        if clock["now"] >= deadline:
            raise SourceContractError("SSEN resource total deadline exceeded")

    transport = ScriptedDeadlineTransport(
        {SEPD_RESOURCE_ID: b"x"},
        on_download=advance_and_enforce,
    )
    if accepted:
        assert download_ssen_hv_resource(
            transport, ssen_resource("SEPD")
        ) == b"x"
    else:
        with pytest.raises(SourceContractError, match="deadline"):
            download_ssen_hv_resource(transport, ssen_resource("SEPD"))


def _install_schema_through_six(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        for version, ddl in MIGRATIONS[:6]:
            connection.executescript(ddl)
            connection.execute(
                "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
                (version,),
            )
        connection.commit()


def _insert_legacy_snapshot_and_event(
    db_path: Path,
    snapshot: SourceSnapshot,
    event: OutageEvent,
    *,
    raw_record: dict[str, Any] | None = None,
) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """INSERT INTO source_snapshots VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot.snapshot_id,
                snapshot.source_dataset_id,
                snapshot.package_id,
                snapshot.source_resource_id,
                snapshot.licence_area,
                snapshot.stable_source_url,
                snapshot.source_modified_at,
                snapshot.fetched_at.isoformat(),
                snapshot.content_sha256,
                snapshot.byte_size,
                snapshot.row_count,
                json.dumps(snapshot.observed_columns),
                snapshot.licence_id,
                snapshot.licence_title,
                snapshot.licence_url,
                snapshot.attribution,
                snapshot.parser_version,
                snapshot.local_snapshot_path,
            ),
        )
        values = event.model_dump()
        values["quality_flags"] = json.dumps(values["quality_flags"])
        values["raw_record"] = json.dumps(
            event.raw_record if raw_record is None else raw_record,
            ensure_ascii=False,
        )
        columns = [
            "quality_flags_json"
            if item == "quality_flags"
            else "raw_record_json"
            if item == "raw_record"
            else item
            for item in OutageEvent.model_fields
        ]
        connection.execute(
            f"INSERT INTO outage_events ({','.join(columns)}) VALUES "
            f"({','.join('?' for _ in columns)})",
            tuple(values[item] for item in OutageEvent.model_fields),
        )
        connection.commit()


def test_migration_seven_adds_immutable_snapshot_version_tables(temp_db: Path) -> None:
    assert run_migrations(temp_db) == 7
    with get_connection(temp_db) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {
        "outage_content_blobs",
        "outage_source_observations",
        "outage_event_versions",
        "outage_reject_versions",
        "current_outage_snapshots",
        "ingestion_run_snapshots",
        "outage_fetch_attempts",
    } <= tables


def test_migration_seven_backfills_legacy_rows_without_inventing_current_state(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
    parsed_event: OutageEvent,
) -> None:
    _install_schema_through_six(temp_db)
    with sqlite3.connect(temp_db) as connection:
        connection.execute(
            """INSERT INTO source_snapshots VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source_snapshot.snapshot_id,
                source_snapshot.source_dataset_id,
                source_snapshot.package_id,
                source_snapshot.source_resource_id,
                source_snapshot.licence_area,
                source_snapshot.stable_source_url,
                source_snapshot.source_modified_at,
                source_snapshot.fetched_at.isoformat(),
                source_snapshot.content_sha256,
                source_snapshot.byte_size,
                source_snapshot.row_count,
                json.dumps(source_snapshot.observed_columns),
                source_snapshot.licence_id,
                source_snapshot.licence_title,
                source_snapshot.licence_url,
                source_snapshot.attribution,
                source_snapshot.parser_version,
                source_snapshot.local_snapshot_path,
            ),
        )
        values = parsed_event.model_dump()
        values["quality_flags"] = json.dumps(values["quality_flags"])
        values["raw_record"] = json.dumps(values["raw_record"])
        columns = [
            "quality_flags_json" if item == "quality_flags" else
            "raw_record_json" if item == "raw_record" else item
            for item in OutageEvent.model_fields
        ]
        connection.execute(
            f"INSERT INTO outage_events ({','.join(columns)}) VALUES "
            f"({','.join('?' for _ in columns)})",
            tuple(values[item] for item in OutageEvent.model_fields),
        )
        connection.commit()

    assert run_migrations(temp_db) == 7
    with get_connection(temp_db) as connection:
        observation = connection.execute(
            "SELECT snapshot_id FROM outage_source_observations"
        ).fetchone()
        blob = connection.execute(
            "SELECT available, relative_snapshot_path FROM outage_content_blobs"
        ).fetchone()
        current = connection.execute(
            "SELECT COUNT(*) FROM current_outage_snapshots"
        ).fetchone()[0]
    assert observation[0] == source_snapshot_id(SEPD_RESOURCE_ID, "abc")
    assert tuple(blob) == (0, None)
    assert current == 0


@pytest.mark.parametrize(
    ("unsafe_kind", "raw_record"),
    [
        (
            "literal",
            {"note": synthetic_signed_target("LEGACY_LITERAL_MARKER")},
        ),
        (
            "repeated_encoded",
            {
                "note": fully_byte_encoded(
                    synthetic_signed_target("LEGACY_REPEATED_MARKER"),
                    9,
                )
            },
        ),
        (
            "malformed_encoded",
            {
                "note": quote(
                    synthetic_signed_target("LEGACY_MALFORMED_MARKER"),
                    safe="",
                )
                + "%GG"
            },
        ),
        (
            "over_budget",
            {"note": "x" * (MAX_PERSISTED_STRING_BYTES + 1)},
        ),
    ],
)
def test_migration_seven_rejects_unsafe_legacy_raw_record_transactionally(
    unsafe_kind: str,
    raw_record: dict[str, Any],
    temp_db: Path,
    source_snapshot: SourceSnapshot,
    parsed_event: OutageEvent,
) -> None:
    del unsafe_kind
    _install_schema_through_six(temp_db)
    _insert_legacy_snapshot_and_event(
        temp_db,
        source_snapshot,
        parsed_event,
        raw_record=raw_record,
    )
    before_raw = json.dumps(raw_record, ensure_ascii=False)

    with pytest.raises(UnsafePersistenceValueError) as caught:
        run_migrations(temp_db)

    assert str(caught.value) == "raw record is unsafe for persistence"
    for value in raw_record.values():
        assert str(value) not in str(caught.value)
    with sqlite3.connect(temp_db) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_version WHERE version=7"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT raw_record_json FROM outage_events"
        ).fetchone()[0] == before_raw
    assert {
        "outage_content_blobs",
        "outage_source_observations",
        "outage_event_versions",
    }.isdisjoint(tables)


def test_migration_seven_preserves_exact_safe_legacy_raw_record_bytes(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
    parsed_event: OutageEvent,
) -> None:
    safe_raw_record = {
        "multiline": "first line\nsecond line",
        "percent": "95%25 and %GG remain exact",
        "unicode": "Shetland Æðey",
    }
    _install_schema_through_six(temp_db)
    _insert_legacy_snapshot_and_event(
        temp_db,
        source_snapshot,
        parsed_event,
        raw_record=safe_raw_record,
    )

    assert run_migrations(temp_db) == 7

    with get_connection(temp_db) as connection:
        event_json = connection.execute(
            "SELECT event_json FROM outage_event_versions"
        ).fetchone()[0]
    migrated_raw = json.loads(event_json)["raw_record"]
    assert migrated_raw == safe_raw_record
    assert json.dumps(
        migrated_raw,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode() == json.dumps(
        safe_raw_record,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def test_legacy_unknown_fetch_time_is_null_and_orders_deterministically(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
) -> None:
    _install_schema_through_six(temp_db)
    first = source_snapshot.model_copy(
        update={
            "snapshot_id": "legacy:z",
            "content_sha256": "1" * 64,
            "local_snapshot_path": "C:/legacy/z.csv",
        }
    )
    second = source_snapshot.model_copy(
        update={
            "snapshot_id": "legacy:a",
            "content_sha256": "2" * 64,
            "local_snapshot_path": "C:/legacy/a.csv",
        }
    )
    with sqlite3.connect(temp_db) as connection:
        for snapshot in (first, second):
            connection.execute(
                """INSERT INTO source_snapshots VALUES
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot.snapshot_id,
                    snapshot.source_dataset_id,
                    snapshot.package_id,
                    snapshot.source_resource_id,
                    snapshot.licence_area,
                    snapshot.stable_source_url,
                    snapshot.source_modified_at,
                    snapshot.fetched_at.isoformat(),
                    snapshot.content_sha256,
                    snapshot.byte_size,
                    0,
                    json.dumps(snapshot.observed_columns),
                    snapshot.licence_id,
                    snapshot.licence_title,
                    snapshot.licence_url,
                    snapshot.attribution,
                    snapshot.parser_version,
                    snapshot.local_snapshot_path,
                ),
            )
        connection.commit()

    assert run_migrations(temp_db) == 7
    unknown = list_source_snapshots(db_path=temp_db)
    assert [item.snapshot_id for item in unknown] == sorted(
        item.snapshot_id for item in unknown
    )
    assert [item.fetched_at for item in unknown] == [None, None]
    serialised = json.dumps(
        [item.model_dump(mode="json") for item in unknown],
        sort_keys=True,
    )
    assert '"fetched_at": null' in serialised
    assert "1970-01-01" not in serialised

    known_digest = "3" * 64
    known = source_snapshot.model_copy(
        update={
            "snapshot_id": source_snapshot_id(SEPD_RESOURCE_ID, known_digest),
            "content_sha256": known_digest,
            "local_snapshot_path": f"blobs/33/{known_digest}.csv",
        }
    )
    save_snapshot(known, db_path=temp_db)
    ordered = list_source_snapshots(db_path=temp_db)
    assert ordered[0].snapshot_id == known.snapshot_id
    assert ordered[0].fetched_at == known.fetched_at
    assert ordered[0].fetched_at is not None
    assert ordered[0].fetched_at.tzinfo is timezone.utc


def test_source_snapshot_requires_unknown_fetch_time_to_be_explicit() -> None:
    data = source_snapshot_data()
    data["fetched_at"] = None

    snapshot = SourceSnapshot(**data)

    assert snapshot.fetched_at is None
    assert snapshot.model_dump(mode="json")["fetched_at"] is None


def test_migration_seven_rejects_conflicting_legacy_snapshot_identity(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
) -> None:
    _install_schema_through_six(temp_db)
    base = (
        source_snapshot.source_dataset_id,
        source_snapshot.package_id,
        source_snapshot.source_resource_id,
        source_snapshot.licence_area,
        source_snapshot.stable_source_url,
        source_snapshot.source_modified_at,
        source_snapshot.fetched_at.isoformat(),
        source_snapshot.content_sha256,
        source_snapshot.byte_size,
        source_snapshot.row_count,
        json.dumps(source_snapshot.observed_columns),
        source_snapshot.licence_id,
        source_snapshot.licence_title,
        source_snapshot.licence_url,
        source_snapshot.attribution,
        source_snapshot.parser_version,
        source_snapshot.local_snapshot_path,
    )
    conflicting = list(base)
    conflicting[11] = "different-licence"
    with sqlite3.connect(temp_db) as connection:
        connection.executemany(
            """INSERT INTO source_snapshots VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                ("legacy:first", *base),
                ("legacy:second", *conflicting),
            ],
        )
        connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        run_migrations(temp_db)

    with sqlite3.connect(temp_db) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_version WHERE version=7"
        ).fetchone()[0] == 0


def test_sync_records_two_snapshots_events_and_rejects_atomically(
    temp_db: Path,
    tmp_path: Path,
    sepd_csv_bytes: bytes,
    shepd_csv_bytes: bytes,
) -> None:
    with sync_client(
        csv_with_invalid_first_row(sepd_csv_bytes), shepd_csv_bytes
    ) as client:
        result = sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=tmp_path / "snapshots", client=client
        )
    assert result.status == "completed"
    assert result.resources_seen == 2
    assert result.rejects_written == 1
    assert len(list_ingestion_run_snapshots(result.run_id, db_path=temp_db)) == 2
    assert len(current_outage_snapshot_ids(db_path=temp_db)) == 2


def test_reject_versions_are_snapshot_scoped_and_stable_across_identical_fetches(
    temp_db: Path,
    tmp_path: Path,
    sepd_csv_bytes: bytes,
    shepd_csv_bytes: bytes,
) -> None:
    sepd = csv_with_invalid_first_row(sepd_csv_bytes)
    results = []
    for _ in range(2):
        with sync_client(sepd, shepd_csv_bytes) as client:
            results.append(sync_ssen_nafirs_hv(
                db_path=temp_db, snapshot_dir=tmp_path / "snapshots", client=client
            ))
    with get_connection(temp_db) as connection:
        rejects = connection.execute(
            "SELECT snapshot_id, reject_id, reject_sha256 FROM outage_reject_versions"
        ).fetchall()
    assert len(rejects) == 1
    assert results[0].rejects_written == results[1].rejects_written == 1


def test_bootstrap_reparse_recreates_exact_reject_ids_and_hashes() -> None:
    detail = json.dumps(
        {"error_message": "invalid", "raw_row": {"value": "bad"}},
        separators=(",", ":"),
        sort_keys=True,
    )
    detail_hash = hashlib.sha256(detail.encode()).hexdigest()
    first = outage_reject_id("snapshot", 2, "invalid_row", detail_hash)
    second = outage_reject_id("snapshot", 2, "invalid_row", detail_hash)
    assert first == second


def test_completed_run_persists_exact_snapshot_associations(
    temp_db: Path,
    tmp_path: Path,
    sepd_csv_bytes: bytes,
    shepd_csv_bytes: bytes,
) -> None:
    with sync_client(sepd_csv_bytes, shepd_csv_bytes) as client:
        result = sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=tmp_path / "snapshots", client=client
        )
    run_ids = tuple(
        item.snapshot_id
        for item in list_ingestion_run_snapshots(result.run_id, db_path=temp_db)
    )
    assert run_ids == current_outage_snapshot_ids(db_path=temp_db)


def test_sync_reuses_identical_content_without_rewriting_snapshot(
    temp_db: Path,
    tmp_path: Path,
    sepd_csv_bytes: bytes,
    shepd_csv_bytes: bytes,
) -> None:
    snapshot_dir = tmp_path / "snapshots"
    with sync_client(sepd_csv_bytes, shepd_csv_bytes) as client:
        first = sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=snapshot_dir, client=client
        )
    mtimes = {path: path.stat().st_mtime_ns for path in snapshot_dir.rglob("*.csv")}
    with sync_client(sepd_csv_bytes, shepd_csv_bytes) as client:
        second = sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=snapshot_dir, client=client
        )
    assert first.snapshots_created == 2
    assert second.snapshots_reused == 2
    assert mtimes == {path: path.stat().st_mtime_ns for path in mtimes}


def test_same_content_in_two_resources_has_distinct_source_snapshot_ids() -> None:
    digest = "a" * 64
    assert source_snapshot_id(SEPD_RESOURCE_ID, digest) != source_snapshot_id(
        SHEPD_RESOURCE_ID, digest
    )


def test_source_observation_existence_is_an_exact_identity_lookup(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
) -> None:
    save_snapshot(source_snapshot, db_path=temp_db)

    assert source_observation_exists(
        source_snapshot.snapshot_id, db_path=temp_db
    ) is True
    assert source_observation_exists("missing", db_path=temp_db) is False


@pytest.mark.parametrize(
    "field",
    ["licence_title", "row_count", "observed_columns_json", "stable_source_url"],
)
def test_snapshot_reuse_validates_every_immutable_field(
    temp_db: Path,
    tmp_path: Path,
    sepd_csv_bytes: bytes,
    shepd_csv_bytes: bytes,
    field: str,
) -> None:
    with sync_client(sepd_csv_bytes, shepd_csv_bytes) as client:
        sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=tmp_path / "snapshots", client=client
        )
    snapshot_id = current_outage_snapshot_ids(db_path=temp_db)[0]
    with get_connection(temp_db) as connection:
        connection.execute(
            f"UPDATE outage_source_observations SET {field} = ? WHERE snapshot_id = ?",
            ("corrupt" if field != "row_count" else 999, snapshot_id),
        )
    with sync_client(sepd_csv_bytes, shepd_csv_bytes) as client:
        result = sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=tmp_path / "snapshots", client=client
        )
    assert result.status == "failed"


def test_snapshot_reuse_ignores_later_fetch_and_source_modified_times(
    temp_db: Path,
    tmp_path: Path,
    sepd_csv_bytes: bytes,
    shepd_csv_bytes: bytes,
) -> None:
    with sync_client(sepd_csv_bytes, shepd_csv_bytes) as client:
        first = sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=tmp_path / "snapshots", client=client
        )
    with sync_client(sepd_csv_bytes, shepd_csv_bytes) as client:
        second = sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=tmp_path / "snapshots", client=client
        )
    assert first.run_id != second.run_id
    assert second.snapshots_reused == 2


def test_snapshot_reuse_cannot_add_to_an_empty_immutable_materialisation(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
    parsed_event: OutageEvent,
) -> None:
    empty = _exact_run_payload(
        source_snapshot,
        parsed_event,
        run_id="run:empty-materialisation",
    )
    empty["events"] = []
    empty["snapshots"] = [
        snapshot.model_copy(update={"row_count": 0})
        for snapshot in empty["snapshots"]
    ]
    commit_ingestion_run(**empty, db_path=temp_db)

    mutated = _exact_run_payload(
        source_snapshot,
        parsed_event,
        run_id="run:mutated-materialisation",
    )
    mutated["snapshots"] = empty["snapshots"]
    with pytest.raises(ValueError, match="exact completed run"):
        commit_ingestion_run(**mutated, db_path=temp_db)


def test_changed_parser_or_canonical_schema_cannot_overwrite_v1_materialization(
    temp_db: Path,
    tmp_path: Path,
    sepd_csv_bytes: bytes,
    shepd_csv_bytes: bytes,
) -> None:
    with sync_client(sepd_csv_bytes, shepd_csv_bytes) as client:
        sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=tmp_path / "snapshots", client=client
        )
    snapshot_id = current_outage_snapshot_ids(db_path=temp_db)[0]
    with get_connection(temp_db) as connection:
        connection.execute(
            "UPDATE outage_source_observations SET parser_version='v2' "
            "WHERE snapshot_id=?",
            (snapshot_id,),
        )
    with sync_client(sepd_csv_bytes, shepd_csv_bytes) as client:
        assert sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=tmp_path / "snapshots", client=client
        ).status == "failed"


def test_unavailable_legacy_blob_becomes_available_only_after_hash_verification(
    temp_db: Path,
    tmp_path: Path,
    sepd_csv_bytes: bytes,
    shepd_csv_bytes: bytes,
) -> None:
    _install_schema_through_six(temp_db)
    resource = ssen_resource("SEPD")
    digest = hashlib.sha256(sepd_csv_bytes).hexdigest()
    legacy_snapshot = SourceSnapshot(
        snapshot_id="legacy:sepd",
        source_dataset_id=resource.source_dataset_id,
        package_id=resource.package_id,
        source_resource_id=resource.source_resource_id,
        licence_area=resource.licence_area,
        stable_source_url=resource.stable_url,
        source_modified_at=None,
        fetched_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        content_sha256=digest,
        byte_size=len(sepd_csv_bytes),
        row_count=2,
        observed_columns=list(SEPD_COLUMNS),
        licence_id="CC-BY-4.0",
        licence_title="Creative Commons Attribution 4.0",
        licence_url="https://creativecommons.org/licenses/by/4.0/",
        attribution="SSEN Distribution",
        parser_version="ssen-nafirs-hv-v1",
        local_snapshot_path="C:/legacy/untrusted.csv",
    )
    with sqlite3.connect(temp_db) as connection:
        connection.execute(
            """INSERT INTO source_snapshots VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                legacy_snapshot.snapshot_id,
                legacy_snapshot.source_dataset_id,
                legacy_snapshot.package_id,
                legacy_snapshot.source_resource_id,
                legacy_snapshot.licence_area,
                legacy_snapshot.stable_source_url,
                None,
                legacy_snapshot.fetched_at.isoformat(),
                legacy_snapshot.content_sha256,
                legacy_snapshot.byte_size,
                legacy_snapshot.row_count,
                json.dumps(legacy_snapshot.observed_columns),
                legacy_snapshot.licence_id,
                legacy_snapshot.licence_title,
                legacy_snapshot.licence_url,
                legacy_snapshot.attribution,
                legacy_snapshot.parser_version,
                legacy_snapshot.local_snapshot_path,
            ),
        )
        connection.commit()
    assert run_migrations(temp_db) == 7

    with sync_client(sepd_csv_bytes, shepd_csv_bytes) as client:
        result = sync_ssen_nafirs_hv(
            db_path=temp_db,
            snapshot_dir=tmp_path / "snapshots",
            client=client,
        )

    assert result.status == "completed"
    assert (result.snapshots_created, result.snapshots_reused) == (1, 1)
    with get_connection(temp_db) as connection:
        blob = connection.execute(
            """SELECT available, relative_snapshot_path
               FROM outage_content_blobs WHERE content_sha256=?""",
            (digest,),
        ).fetchone()
    assert blob[0] == 1
    assert blob[1] == f"blobs/{digest[:2]}/{digest}.csv"


def test_repeated_fetch_records_attempt_without_mutating_snapshot(
    temp_db: Path,
    tmp_path: Path,
    sepd_csv_bytes: bytes,
    shepd_csv_bytes: bytes,
) -> None:
    for _ in range(2):
        with sync_client(sepd_csv_bytes, shepd_csv_bytes) as client:
            sync_ssen_nafirs_hv(
                db_path=temp_db, snapshot_dir=tmp_path / "snapshots", client=client
            )
    with get_connection(temp_db) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM outage_source_observations"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM outage_fetch_attempts"
        ).fetchone()[0] == 4


def test_fetch_manifest_is_complete_safe_and_contains_no_request_query(
    temp_db: Path,
    tmp_path: Path,
    sepd_csv_bytes: bytes,
    shepd_csv_bytes: bytes,
) -> None:
    with sync_client(sepd_csv_bytes, shepd_csv_bytes, token="TOPSECRET") as client:
        result = sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=tmp_path / "snapshots", client=client
        )
    manifest = build_ssen_fetch_manifest(result.run_id, db_path=temp_db)
    text = manifest.model_dump_json()
    assert len(manifest.attempts) == 2
    assert "TOPSECRET" not in text
    assert "X-Amz" not in text


def test_changed_event_is_versioned_in_both_old_and_new_snapshots(
    temp_db: Path,
    tmp_path: Path,
    sepd_csv_bytes: bytes,
    shepd_csv_bytes: bytes,
) -> None:
    snapshot_dir = tmp_path / "snapshots"
    with sync_client(sepd_csv_bytes, shepd_csv_bytes) as client:
        first = sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=snapshot_dir, client=client
        )
    changed_rows = list(csv.reader(io.StringIO(sepd_csv_bytes.decode())))
    customers_index = changed_rows[0].index("HV_CUST_AFF")
    changed_rows[1][customers_index] = "4"
    changed_stream = io.StringIO(newline="")
    csv.writer(changed_stream, lineterminator="\n").writerows(changed_rows)
    changed = changed_stream.getvalue().encode()
    with sync_client(changed, shepd_csv_bytes) as client:
        second = sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=snapshot_dir, client=client
        )
    old_ids = tuple(item.snapshot_id for item in list_ingestion_run_snapshots(
        first.run_id, db_path=temp_db
    ))
    new_ids = tuple(item.snapshot_id for item in list_ingestion_run_snapshots(
        second.run_id, db_path=temp_db
    ))
    old = {item.event_id: item for item in list_outage_event_versions(old_ids, db_path=temp_db)}
    new = {item.event_id: item for item in list_outage_event_versions(new_ids, db_path=temp_db)}
    common = set(old) & set(new)
    assert common
    assert any(old[item].customers_affected != new[item].customers_affected for item in common)


def test_removed_event_disappears_from_current_but_remains_in_old_snapshot(
    temp_db: Path,
    tmp_path: Path,
    sepd_csv_bytes: bytes,
    shepd_csv_bytes: bytes,
) -> None:
    with sync_client(sepd_csv_bytes, shepd_csv_bytes) as client:
        first = sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=tmp_path / "snapshots", client=client
        )
    old_ids = tuple(item.snapshot_id for item in list_ingestion_run_snapshots(
        first.run_id, db_path=temp_db
    ))
    with sync_client(first_csv_row_only(sepd_csv_bytes), shepd_csv_bytes) as client:
        sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=tmp_path / "snapshots", client=client
        )
    old_events = list_outage_event_versions(old_ids, db_path=temp_db)
    current = resolve_outage_evidence_scope(db_path=temp_db)
    current_events = list_outage_event_versions(current.snapshot_ids, db_path=temp_db)
    assert len(old_events) == len(current_events) + 1


def test_old_manifest_snapshot_set_replays_after_later_sync(
    temp_db: Path,
    tmp_path: Path,
    sepd_csv_bytes: bytes,
    shepd_csv_bytes: bytes,
) -> None:
    with sync_client(sepd_csv_bytes, shepd_csv_bytes) as client:
        first = sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=tmp_path / "snapshots", client=client
        )
    old = tuple(item.snapshot_id for item in list_ingestion_run_snapshots(
        first.run_id, db_path=temp_db
    ))
    before = [item.model_dump() for item in list_outage_event_versions(old, db_path=temp_db)]
    with sync_client(first_csv_row_only(sepd_csv_bytes), shepd_csv_bytes) as client:
        sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=tmp_path / "snapshots", client=client
        )
    assert before == [item.model_dump() for item in list_outage_event_versions(old, db_path=temp_db)]


def test_current_snapshot_pointer_advances_for_both_resources_atomically(
    temp_db: Path,
    tmp_path: Path,
    sepd_csv_bytes: bytes,
    shepd_csv_bytes: bytes,
) -> None:
    with sync_client(sepd_csv_bytes, shepd_csv_bytes) as client:
        first = sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=tmp_path / "snapshots", client=client
        )
    old = current_outage_snapshot_ids(db_path=temp_db)
    with sync_client(first_csv_row_only(sepd_csv_bytes), shepd_csv_bytes) as client:
        second = sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=tmp_path / "snapshots", client=client
        )
    new = current_outage_snapshot_ids(db_path=temp_db)
    assert old != new
    with get_connection(temp_db) as connection:
        assert {row[0] for row in connection.execute(
            "SELECT run_id FROM current_outage_snapshots"
        )} == {second.run_id}
    assert first.run_id != second.run_id


def test_sync_cleans_first_snapshot_when_second_download_fails(
    temp_db: Path,
    tmp_path: Path,
    sepd_csv_bytes: bytes,
    shepd_csv_bytes: bytes,
) -> None:
    snapshot_dir = tmp_path / "snapshots"
    with sync_client(
        sepd_csv_bytes,
        shepd_csv_bytes,
        fail_resource_id=SEPD_RESOURCE_ID,
    ) as client:
        result = sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=snapshot_dir, client=client
        )
    assert result.status == "failed"
    assert list(snapshot_dir.rglob("*.csv")) == []


def test_sync_cleans_new_files_but_preserves_preexisting_snapshot(
    temp_db: Path,
    tmp_path: Path,
    sepd_csv_bytes: bytes,
    shepd_csv_bytes: bytes,
) -> None:
    snapshot_dir = tmp_path / "snapshots"
    with sync_client(sepd_csv_bytes, shepd_csv_bytes) as client:
        sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=snapshot_dir, client=client
        )
    before = {path: path.read_bytes() for path in snapshot_dir.rglob("*.csv")}
    with sync_client(
        sepd_csv_bytes,
        shepd_csv_bytes,
        fail_resource_id=SEPD_RESOURCE_ID,
    ) as client:
        sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=snapshot_dir, client=client
        )
    assert before == {path: path.read_bytes() for path in before}


def test_sync_persistence_failure_leaves_only_one_failed_run(
    monkeypatch: pytest.MonkeyPatch,
    temp_db: Path,
    tmp_path: Path,
    sepd_csv_bytes: bytes,
    shepd_csv_bytes: bytes,
) -> None:
    monkeypatch.setattr(
        "app.outage_source.commit_ingestion_run",
        lambda **_: (_ for _ in ()).throw(sqlite3.OperationalError("synthetic")),
    )
    with sync_client(sepd_csv_bytes, shepd_csv_bytes) as client:
        result = sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=tmp_path / "snapshots", client=client
        )
    with get_connection(temp_db) as connection:
        runs = connection.execute(
            "SELECT run_id, status FROM ingestion_runs"
        ).fetchall()
    assert [tuple(row) for row in runs] == [(result.run_id, "failed")]


def test_sync_signed_target_never_crosses_output_log_file_or_sqlite(
    temp_db: Path,
    tmp_path: Path,
    sepd_csv_bytes: bytes,
    shepd_csv_bytes: bytes,
    caplog: pytest.LogCaptureFixture,
) -> None:
    marker = "SYNTHETIC_SIGNED_TARGET_MUST_NOT_PERSIST"
    snapshot_dir = tmp_path / "snapshots"
    with sync_client(sepd_csv_bytes, shepd_csv_bytes, token=marker) as client:
        result = sync_ssen_nafirs_hv(
            db_path=temp_db, snapshot_dir=snapshot_dir, client=client
        )
    with get_connection(temp_db) as connection:
        sqlite_text = "\n".join(connection.iterdump())
    output = result.model_dump_json() + caplog.text + sqlite_text
    output += "".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in snapshot_dir.rglob("*")
        if path.is_file()
    )
    assert marker not in output
    assert "X-Amz-Signature" not in output


def test_source_manifest_matches_exact_reviewed_contract() -> None:
    manifest = load_ssen_source_manifest()
    assert manifest.source_dataset_id == "nafirs-hv-faults"
    assert manifest.package_id == "b0a58349-2ce6-4fa8-9238-a5564f966433"
    assert manifest.request_method == "GET"
    assert manifest.timezone_name is None
    assert manifest.publisher_cadence is None
    assert {item.source_resource_id for item in manifest.resources} == {
        SEPD_RESOURCE_ID,
        SHEPD_RESOURCE_ID,
    }


def test_source_manifest_explicitly_permits_attributed_source_byte_redistribution() -> None:
    manifest = load_ssen_source_manifest()
    assert manifest.source_byte_redistribution == "permitted_with_attribution"
    assert manifest.licence_evidence.source_byte_redistribution == (
        "permitted_with_attribution"
    )


def test_source_manifest_binds_exact_licence_evidence_hash_and_observation() -> None:
    evidence = load_ssen_source_manifest().licence_evidence
    assert evidence.catalogue_observation_id == (
        "ssen:725a8a6de949f32e6b5680e04fc447f8e80814ed7412f26129fca75c9014d6a7"
    )
    assert evidence.catalogue_observation_content_sha256 == (
        "592181ea19d3d8550539441a8674179488cc2409b0b970307fb883ebdf6eecae"
    )
    assert evidence.observed_at == datetime(
        2026, 7, 31, 10, 6, 47, 336819, tzinfo=timezone.utc
    )


def test_source_manifest_verifies_hash_addressed_licence_evidence_artifact() -> None:
    manifest = load_ssen_source_manifest()
    artifact_path = Path(manifest.licence_evidence.evidence_artifact_path)
    artifact_bytes = artifact_path.read_bytes()
    assert artifact_bytes.endswith(b"\n")
    assert not artifact_bytes.endswith(b"\n\n")
    assert hashlib.sha256(artifact_bytes).hexdigest() == (
        manifest.licence_evidence.evidence_artifact_sha256
    )
    assert SourceLicenceEvidenceArtifactV1.model_validate_json(
        artifact_bytes
    ).model_dump(mode="json") == {
        key: value
        for key, value in manifest.licence_evidence.model_dump(mode="json").items()
        if key not in {"evidence_artifact_path", "evidence_artifact_sha256", "evidence_sha256"}
    }


def test_licence_evidence_git_materialisation_preserves_exact_lf_bytes(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    source_artifact = (
        repository_root / "data/sources/evidence/ssen-nafirs-hv-licence.json"
    )
    source_attributes = repository_root / ".gitattributes"
    isolated = tmp_path / "git-materialisation"
    artifact = isolated / "data/sources/evidence/ssen-nafirs-hv-licence.json"
    artifact.parent.mkdir(parents=True)
    shutil.copy2(source_artifact, artifact)
    shutil.copy2(source_attributes, isolated / ".gitattributes")
    expected = source_artifact.read_bytes()

    subprocess.run(["git", "init", "-q"], cwd=isolated, check=True)
    subprocess.run(
        ["git", "config", "core.autocrlf", "true"], cwd=isolated, check=True
    )
    subprocess.run(
        [
            "git",
            "add",
            "--",
            ".gitattributes",
            "data/sources/evidence/ssen-nafirs-hv-licence.json",
        ],
        cwd=isolated,
        check=True,
    )
    artifact.unlink()
    subprocess.run(
        [
            "git",
            "checkout-index",
            "-f",
            "--",
            "data/sources/evidence/ssen-nafirs-hv-licence.json",
        ],
        cwd=isolated,
        check=True,
    )

    materialised = artifact.read_bytes()
    assert materialised == expected
    assert materialised.endswith(b"\n")
    assert b"\r" not in materialised
    assert hashlib.sha256(materialised).hexdigest() == (
        "1b169f3a400a5b6c17962d8a6ad1d27b897c9fa231d3b880bd6a269c54528f68"
    )


def test_outage_cli_exposes_only_local_sync(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        outage_cli_main(["--help"])
    output = capsys.readouterr().out
    assert caught.value.code == 0
    assert "sync" in output
    assert "ssen-nafirs-hv" in output
    for forbidden in ("bid", "dispatch", "login", "oauth", "write"):
        assert forbidden not in output.lower()


def test_outage_cli_help_runs_as_module() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "app.outage_cli", "--help"],
        env={**dict(__import__("os").environ), "PYTHONPATH": "backend"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "sync" in completed.stdout
    assert "ssen-nafirs-hv" in completed.stdout
    current_outage_snapshot_ids,
    list_ingestion_run_snapshots,
    list_outage_event_versions,

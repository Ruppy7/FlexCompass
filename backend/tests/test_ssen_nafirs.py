"""Focused contracts for SSEN NaFIRS outage evidence models."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx
import pytest
from app.db import MIGRATIONS, get_connection, run_migrations
from app.outage_store import (
    commit_ingestion_run,
    count_outage_events,
    count_source_snapshots,
    get_outage_event,
    list_outage_events,
    list_source_snapshots,
    record_failed_ingestion_run,
    save_snapshot,
    summarise_outage_events,
    upsert_outage_events,
)
from app.outages import (
    OutageEvent,
    OutageReject,
    OutageSummary,
    SourceResource,
    SourceSnapshot,
    SourceSnapshotPublic,
    SyncResult,
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
        "fetched_at": datetime,
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
        "fetched_at": datetime,
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


def test_outage_schema_migrates_with_required_tables_and_indexes(
    temp_db: Path,
) -> None:
    assert run_migrations(temp_db) == 6
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

    assert run_migrations(temp_db) == 6
    assert run_migrations(temp_db) == 6
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


def test_event_upsert_round_trips_json_and_updates_evidence(
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
    assert upsert_outage_events([updated], db_path=temp_db) == 1

    rows = list_outage_events(db_path=temp_db)
    assert len(rows) == 1
    assert rows[0] == updated
    assert get_outage_event(updated.event_id, db_path=temp_db) == updated
    assert get_outage_event("missing", db_path=temp_db) is None


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

    assert [item.event_id for item in list_outage_events(
        limit=2, offset=0, db_path=temp_db
    )] == ["event-a", "event-b"]
    assert [item.event_id for item in list_outage_events(
        limit=2, offset=2, db_path=temp_db
    )] == ["event-c"]
    assert list_outage_events(limit=2, offset=3, db_path=temp_db) == []
    assert list_outage_events(limit=2, offset=9, db_path=temp_db) == []
    filters = {
        "licence_area": "SHEPD",
        "district_short_code": "SWIN",
        "reporting_year": 2025,
        "cause_code": "11",
        "db_path": temp_db,
    }
    assert count_outage_events(**filters) == 1
    assert [item.event_id for item in list_outage_events(**filters)] == ["event-b"]
    assert summarise_outage_events(
        licence_area="SHEPD", reporting_year=2025, db_path=temp_db
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
        licence_area="SEPD", reporting_year=2026, db_path=temp_db
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

    result = commit_ingestion_run(
        run_id="run:complete",
        resources_seen=2,
        snapshots=[source_snapshot],
        events=[parsed_event],
        rejects=[reject],
        snapshots_created=1,
        snapshots_reused=0,
        warnings=["publisher cadence remains unknown"],
        db_path=temp_db,
    )

    assert result.status == "completed"
    assert result.events_written == 1
    assert result.rejects_written == 1
    with get_connection(temp_db) as connection:
        run = connection.execute(
            "SELECT status FROM ingestion_runs WHERE run_id = ?", ("run:complete",)
        ).fetchone()
        reject_json = connection.execute(
            "SELECT raw_row_json FROM outage_rejects"
        ).fetchone()[0]
    assert run[0] == "completed"
    assert json.loads(reject_json) == {
        "HV_INCIDENT_TIME": "not-a-date",
        "signed_url": "[REDACTED]",
    }
    assert marker not in reject_json


def test_commit_ingestion_run_rolls_back_running_row_and_all_payloads(
    temp_db: Path,
    source_snapshot: SourceSnapshot,
    parsed_event: OutageEvent,
) -> None:
    invalid_event = parsed_event.model_copy(
        update={"source_snapshot_id": "sha256:missing"}
    )

    with pytest.raises(sqlite3.IntegrityError):
        commit_ingestion_run(
            run_id="run:rollback",
            resources_seen=1,
            snapshots=[source_snapshot],
            events=[invalid_event],
            rejects=[],
            snapshots_created=1,
            snapshots_reused=0,
            warnings=[],
            db_path=temp_db,
        )

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
    assert counts == {
        "source_snapshots": 0,
        "ingestion_runs": 0,
        "outage_events": 0,
        "outage_rejects": 0,
    }


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
    assert json.loads(row[2]) == [{"signed_url": "[REDACTED]"}, "safe warning"]
    assert marker not in payload
    assert "X-Amz-Signature" not in payload
    assert count_source_snapshots(db_path=temp_db) == 0
    assert count_outage_events(db_path=temp_db) == 0


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

    completed = commit_ingestion_run(
        run_id="run:signed-completed",
        resources_seen=1,
        snapshots=[source_snapshot],
        events=[parsed_event],
        rejects=[reject],
        snapshots_created=1,
        snapshots_reused=0,
        warnings=[
            "preserve ordinary completed warning",
            signed_url,
            nested_payload,
            f"prefix X-Amz-Algorithm={markers['X-Amz-Algorithm']} suffix",
        ],
        db_path=temp_db,
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
    assert "ordinary reject context" in sqlite_text
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

    completed = commit_ingestion_run(
        run_id="run:encoded-completed",
        resources_seen=1,
        snapshots=[source_snapshot],
        events=[parsed_event],
        rejects=[reject],
        snapshots_created=1,
        snapshots_reused=0,
        warnings=[
            "preserve ordinary encoded completed warning",
            encoded_url,
            double_encoded_url,
            encoded_mixed_url,
            fully_encoded_url,
            double_fully_encoded_url,
            encoded_payload,
        ],
        db_path=temp_db,
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

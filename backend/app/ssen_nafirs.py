"""Strict contracts for public SSEN NaFIRS HV outage evidence."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from app.catalogue_sync import redact
from app.outages import LicenceArea, OutageEvent, SourceResource

SOURCE_DATASET_ID = "nafirs-hv-faults"
PACKAGE_ID = "b0a58349-2ce6-4fa8-9238-a5564f966433"
PACKAGE_SHOW_URL = (
    "https://data-api.ssen.co.uk/api/3/action/"
    "package_show?id=nafirs-hv-faults"
)
LICENCE_ID = "CC-BY-4.0"
LICENCE_TITLE = "Creative Commons Attribution 4.0"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"

SEPD_RESOURCE_ID = "ab32515f-76f2-421d-8034-7d5b01325a33"
SHEPD_RESOURCE_ID = "673578c9-f531-41a5-a17c-0b35bc0fae4c"

SEPD_COLUMNS = (
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

SHEPD_COLUMNS = (
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

_RESOURCE_CONTRACTS: dict[LicenceArea, tuple[str, str]] = {
    "SEPD": (SEPD_RESOURCE_ID, "NaFIRS HV Faults SEPD (CSV)"),
    "SHEPD": (SHEPD_RESOURCE_ID, "NaFIRS HV Faults SHEPD (CSV)"),
}
_INTEGER_SYNTAX = re.compile(r"[+-]?[0-9]+\Z")


class SourceContractError(ValueError):
    """A fail-closed mismatch in public source metadata or schema."""

    def __init__(self, message: str, *, observed: Any = None) -> None:
        self.observed = redact(observed)
        suffix = (
            ""
            if observed is None
            else f"; observed={json.dumps(self.observed, sort_keys=True)}"
        )
        super().__init__(f"{message}{suffix}")


class OutageRowError(ValueError):
    """A stable, safe rejection of one contract-valid CSV row."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        raw_record: Mapping[str, Any] | None = None,
        row_number: int | None = None,
    ) -> None:
        self.code = code
        self.message = str(redact(message))
        self.raw_record = dict(raw_record or {})
        self.row_number = row_number
        super().__init__(self.message)


def _columns_for(licence_area: LicenceArea) -> tuple[str, ...]:
    return SEPD_COLUMNS if licence_area == "SEPD" else SHEPD_COLUMNS


def _normalise(value: str) -> str:
    return " ".join(value.split())


def _required(
    row: Mapping[str, str],
    field: str,
    raw_record: Mapping[str, Any],
) -> str:
    value = _normalise(row[field])
    if not value:
        raise OutageRowError(
            "missing_required_field",
            "a required outage field is blank",
            raw_record=raw_record,
        )
    return value


def _reporting_year(row: Mapping[str, str], raw_record: Mapping[str, Any]) -> int:
    value = _required(row, "REPORTING_YEAR", raw_record)
    if _INTEGER_SYNTAX.fullmatch(value) is None:
        raise OutageRowError(
            "invalid_reporting_year",
            "reporting year is not a base-10 integer",
            raw_record=raw_record,
        )
    try:
        year = int(value, 10)
    except ValueError as error:
        raise OutageRowError(
            "invalid_reporting_year",
            "reporting year is not a supported base-10 integer",
            raw_record=raw_record,
        ) from error
    if not 1900 <= year <= 2100:
        raise OutageRowError(
            "invalid_reporting_year",
            "reporting year is outside the accepted evidence domain",
            raw_record=raw_record,
        )
    return year


def _incident_time(
    row: Mapping[str, str],
    raw_record: Mapping[str, Any],
) -> str:
    value = _required(row, "HV_INCIDENT_TIME", raw_record)
    try:
        parsed = datetime.strptime(value, "%d/%m/%Y %H:%M")
    except ValueError as error:
        raise OutageRowError(
            "invalid_incident_time",
            "incident time is not a valid day-first local civil time",
            raw_record=raw_record,
        ) from error
    return parsed.isoformat(timespec="seconds")


def _optional_string(row: Mapping[str, str], field: str) -> str | None:
    value = _normalise(row[field])
    return value or None


def _optional_float(
    row: Mapping[str, str],
    field: str,
    *,
    positive: bool,
    flag: str,
    quality_flags: list[str],
) -> float | None:
    value = _normalise(row[field])
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError:
        quality_flags.append(flag)
        return None
    if not math.isfinite(parsed) or (parsed <= 0 if positive else parsed < 0):
        quality_flags.append(flag)
        return None
    return parsed


def _optional_non_negative_int(
    row: Mapping[str, str],
    field: str,
    *,
    flag: str,
    quality_flags: list[str],
) -> int | None:
    value = _normalise(row[field])
    if not value:
        return None
    if _INTEGER_SYNTAX.fullmatch(value) is None:
        quality_flags.append(flag)
        return None
    try:
        parsed = int(value, 10)
    except ValueError:
        quality_flags.append(flag)
        return None
    if parsed < 0:
        quality_flags.append(flag)
        return None
    return parsed


def _event_id(
    *,
    source_dataset_id: str,
    source_resource_id: str,
    licence_area: LicenceArea,
    raw_record: Mapping[str, str],
    network_field: str,
) -> str:
    evidence = {
        "source_dataset_id": source_dataset_id,
        "source_resource_id": source_resource_id,
        "licence_area": licence_area,
        "district_hv_reference": raw_record["DIST_HV_REF"],
        "incident_time": raw_record["HV_INCIDENT_TIME"],
        "network_reference": raw_record[network_field],
    }
    canonical = json.dumps(
        evidence,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def parse_ssen_hv_event(
    row: dict[str, str],
    *,
    licence_area: Literal["SEPD", "SHEPD"],
    source_dataset_id: str,
    source_resource_id: str,
    snapshot_id: str,
) -> OutageEvent:
    """Parse one raw SSEN row without losing its original evidence."""
    expected_columns = _columns_for(licence_area)
    if tuple(row) != expected_columns:
        raise SourceContractError(
            f"{licence_area} row columns do not match the raw CSV contract",
            observed=list(row),
        )

    raw_record = dict(row)
    network_field = "NRN_SOUTH" if licence_area == "SEPD" else "NRN_NORTH"
    average_field = (
        "AVG_TIME_OFF_SUPPLY_MINS"
        if licence_area == "SEPD"
        else "AVG_TIME_OFF_MINS"
    )
    quality_flags: list[str] = []

    district_short_code = _required(row, "DISTRICT_SHORT_CODE", raw_record)
    district_hv_reference = _required(row, "DIST_HV_REF", raw_record)
    network_reference = _required(row, network_field, raw_record)
    reporting_year = _reporting_year(row, raw_record)
    incident_started_local = _incident_time(row, raw_record)

    voltage_kv = _optional_float(
        row,
        "VOLTAGE_1",
        positive=True,
        flag="invalid_voltage_kv",
        quality_flags=quality_flags,
    )
    customers_affected = _optional_non_negative_int(
        row,
        "HV_CUST_AFF",
        flag="invalid_customers_affected",
        quality_flags=quality_flags,
    )
    customer_minutes_lost = _optional_non_negative_int(
        row,
        "HV_CUST_MINS_LOST",
        flag="invalid_customer_minutes_lost",
        quality_flags=quality_flags,
    )
    average_minutes_off_supply = _optional_float(
        row,
        average_field,
        positive=False,
        flag="invalid_average_minutes_off_supply",
        quality_flags=quality_flags,
    )

    return OutageEvent(
        event_id=_event_id(
            source_dataset_id=source_dataset_id,
            source_resource_id=source_resource_id,
            licence_area=licence_area,
            raw_record=raw_record,
            network_field=network_field,
        ),
        source_dataset_id=source_dataset_id,
        source_resource_id=source_resource_id,
        source_snapshot_id=snapshot_id,
        operator="SSEN Distribution",
        licence_area=licence_area,
        incident_started_local=incident_started_local,
        timezone_name=None,
        reporting_year=reporting_year,
        voltage_kv=voltage_kv,
        district_short_code=district_short_code,
        district_hv_reference=district_hv_reference,
        network_reference=network_reference,
        primary_nrn=(
            _optional_string(row, "PRIMARY_NRN") if licence_area == "SHEPD" else None
        ),
        primary_name=(
            _optional_string(row, "PRIMARY_NAME") if licence_area == "SHEPD" else None
        ),
        customers_affected=customers_affected,
        customer_minutes_lost=customer_minutes_lost,
        average_minutes_off_supply=average_minutes_off_supply,
        equipment_code=_optional_string(row, "EQUIPMENT_CODE"),
        equipment=_optional_string(row, "EQUIPMENT"),
        component_code=_optional_string(row, "COMPONENT_CODE"),
        component=_optional_string(row, "COMPONENT"),
        cause_code=_optional_string(row, "CAUSE_CODE"),
        cause=_optional_string(row, "CAUSE"),
        contributory_cause_code=_optional_string(
            row, "CONTRIBUTORY_CAUSE_CODE"
        ),
        contributory_cause=_optional_string(row, "CONTRIBUTORY_CAUSE"),
        damage=_optional_string(row, "DAMAGE"),
        exceptional_event=_optional_string(row, "EXCEPTIONAL_EVENT"),
        quality_flags=quality_flags,
        raw_record=raw_record,
    )


def iter_ssen_hv_csv(
    content: bytes,
    *,
    licence_area: LicenceArea,
    source_dataset_id: str = SOURCE_DATASET_ID,
    source_resource_id: str | None = None,
    snapshot_id: str = "unpersisted",
) -> Iterator[OutageEvent | OutageRowError]:
    """Yield events and row rejects after validating the exact raw header."""
    expected_columns = _columns_for(licence_area)
    resolved_resource_id = source_resource_id or _RESOURCE_CONTRACTS[licence_area][0]
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise SourceContractError("SSEN CSV is not valid UTF-8") from error

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        observed_header = next(reader)
    except StopIteration:
        observed_header = []
    except csv.Error as error:
        raise SourceContractError("SSEN CSV header is malformed") from error
    if tuple(observed_header) != expected_columns:
        raise SourceContractError(
            f"{licence_area} CSV header does not match the raw contract",
            observed=observed_header,
        )

    while True:
        row_number = reader.line_num + 1
        previous_line_number = reader.line_num
        try:
            values = next(reader)
        except StopIteration:
            break
        except csv.Error:
            yield OutageRowError(
                "invalid_row_shape",
                "CSV row structure is malformed",
                row_number=row_number,
            )
            if reader.line_num <= previous_line_number:
                break
            continue

        if len(values) != len(expected_columns):
            yield OutageRowError(
                "invalid_row_shape",
                "CSV row value count does not match the validated header",
                raw_record={"_row": values},
                row_number=row_number,
            )
            continue
        row = dict(zip(expected_columns, values, strict=True))
        try:
            yield parse_ssen_hv_event(
                row,
                licence_area=licence_area,
                source_dataset_id=source_dataset_id,
                source_resource_id=resolved_resource_id,
                snapshot_id=snapshot_id,
            )
        except OutageRowError as error:
            error.row_number = row_number
            yield error


def _resource_url_is_valid(url: Any, resource_id: str) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    expected_prefix = (
        f"/dataset/{PACKAGE_ID}/resource/{resource_id}/download/"
    )
    filename = parsed.path.removeprefix(expected_prefix)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "data-api.ssen.co.uk"
        and parsed.username is None
        and parsed.password is None
        and port is None
        and parsed.query == ""
        and parsed.fragment == ""
        and parsed.path.startswith(expected_prefix)
        and bool(filename)
        and "/" not in filename
    )


def _require_package_contract(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise SourceContractError("SSEN package response did not report success")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise SourceContractError("SSEN package result is missing")

    expected_package = {
        "id": PACKAGE_ID,
        "name": SOURCE_DATASET_ID,
        "license_id": LICENCE_ID,
        "license_title": LICENCE_TITLE,
        "license_url": LICENCE_URL,
    }
    observed_package = {key: result.get(key) for key in expected_package}
    if observed_package != expected_package:
        raise SourceContractError(
            "SSEN package identity or licence contract changed",
            observed=observed_package,
        )
    resources = result.get("resources")
    if not isinstance(resources, list) or not all(
        isinstance(resource, dict) for resource in resources
    ):
        raise SourceContractError("SSEN package resources are malformed")
    return resources


def _is_active_csv(resource: Mapping[str, Any]) -> bool:
    media_type = str(resource.get("mimetype", "")).split(";", 1)[0].strip().lower()
    return resource.get("datastore_active") is True and (
        str(resource.get("format", "")).upper() == "CSV"
        or media_type == "text/csv"
    )


def discover_ssen_hv_resources(client: httpx.Client) -> list[SourceResource]:
    """Discover only the two exact active public NaFIRS HV CSV resources."""
    if client.follow_redirects:
        raise SourceContractError("SSEN package discovery must not follow redirects")
    try:
        response = client.get(PACKAGE_SHOW_URL)
        response.raise_for_status()
        resources = _require_package_contract(response.json())
    except SourceContractError:
        raise
    except (httpx.HTTPError, ValueError) as error:
        raise SourceContractError("SSEN package discovery failed safely") from error

    active_csvs = [
        resource
        for resource in resources
        if _is_active_csv(resource)
    ]
    expected_ids = {SEPD_RESOURCE_ID, SHEPD_RESOURCE_ID}
    if len(active_csvs) != 2 or {
        resource.get("id") for resource in active_csvs
    } != expected_ids:
        raise SourceContractError(
            "active SSEN CSV resource set changed",
            observed=[
                {
                    "id": resource.get("id"),
                    "name": resource.get("name"),
                    "format": resource.get("format"),
                    "datastore_active": resource.get("datastore_active"),
                }
                for resource in active_csvs
            ],
        )

    discovered: list[SourceResource] = []
    for licence_area, (resource_id, expected_name) in _RESOURCE_CONTRACTS.items():
        matches = [
            resource for resource in resources if resource.get("id") == resource_id
        ]
        if len(matches) != 1:
            raise SourceContractError(
                f"{licence_area} SSEN resource is missing or duplicated",
                observed=[resource.get("id") for resource in resources],
            )
        resource = matches[0]
        if (
            resource.get("name") != expected_name
            or resource.get("format") != "CSV"
            or resource.get("datastore_active") is not True
            or not _resource_url_is_valid(resource.get("url"), resource_id)
        ):
            raise SourceContractError(
                f"{licence_area} SSEN resource contract changed",
                observed={
                    "id": resource.get("id"),
                    "name": resource.get("name"),
                    "url": resource.get("url"),
                    "format": resource.get("format"),
                    "datastore_active": resource.get("datastore_active"),
                },
            )
        try:
            source_resource = SourceResource(
                source_dataset_id=SOURCE_DATASET_ID,
                package_id=PACKAGE_ID,
                source_resource_id=resource_id,
                licence_area=licence_area,
                name=expected_name,
                stable_url=resource["url"],
                source_modified_at=resource.get("last_modified"),
                format=resource["format"],
                media_type=resource.get("mimetype"),
                datastore_active=resource["datastore_active"],
                raw_record=dict(resource),
            )
        except ValidationError:
            raise SourceContractError(
                f"{licence_area} SSEN resource fields are invalid"
            ) from None
        discovered.append(source_resource)
    return discovered

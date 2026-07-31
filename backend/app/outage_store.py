"""Immutable SQLite persistence and deterministic outage evidence queries."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.catalogue_sync import safe_error
from app.config import config
from app.db import get_connection, run_migrations
from app.outages import (
    CANONICAL_EVENT_SCHEMA_VERSION,
    LicenceArea,
    OutageEvent,
    OutageEvidenceScopeV1,
    OutageFetchAttemptPublicV1,
    OutageReject,
    OutageSummary,
    SourceSnapshot,
    SsenFetchManifestV1,
    SyncResult,
    outage_reject_id,
)
from app.persistence_safety import (
    UNSAFE_VALUE_SENTINEL,
    require_exact_safe_raw_record,
    sanitise_diagnostic_value,
)
from app.ssen_nafirs import SEPD_RESOURCE_ID, SHEPD_RESOURCE_ID

_EXPECTED_RESOURCE_IDS = tuple(sorted((SEPD_RESOURCE_ID, SHEPD_RESOURCE_ID)))
_EVENT_FILTERS = {
    "licence_area": "licence_area",
    "district_short_code": "district_short_code",
    "reporting_year": "reporting_year",
    "cause_code": "cause_code",
}


def _db_path(db_path: Path | None) -> Path:
    return db_path or config.outage_db_path


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256_json(value: Any) -> tuple[str, str]:
    encoded = _json(value)
    return encoded, hashlib.sha256(encoded.encode()).hexdigest()


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("outage timestamps must include a timezone")
    return value.astimezone(timezone.utc).isoformat()


def _validate_limit_offset(limit: int, offset: int) -> None:
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if offset < 0:
        raise ValueError("offset must be non-negative")


def _validate_stable_source_url(value: str) -> None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError("snapshot provenance requires a stable SSEN source URL") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname != "data-api.ssen.co.uk"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("snapshot provenance requires a stable SSEN source URL")


def _observation_values(snapshot: SourceSnapshot) -> tuple[Any, ...]:
    _validate_stable_source_url(snapshot.stable_source_url)
    return (
        snapshot.snapshot_id,
        snapshot.source_dataset_id,
        snapshot.package_id,
        snapshot.source_resource_id,
        snapshot.licence_area,
        snapshot.stable_source_url,
        snapshot.content_sha256,
        snapshot.row_count,
        _json(snapshot.observed_columns),
        snapshot.licence_id,
        snapshot.licence_title,
        snapshot.licence_url,
        snapshot.attribution,
        snapshot.parser_version,
        "ssen-nafirs-hv-v1",
        CANONICAL_EVENT_SCHEMA_VERSION,
    )


def _event_materialisation(event: OutageEvent) -> tuple[Any, ...]:
    require_exact_safe_raw_record(event.raw_record)
    event_json, event_sha256 = _sha256_json(event.model_dump(mode="json"))
    return (
        event.source_snapshot_id,
        event.event_id,
        event.source_resource_id,
        event.licence_area,
        event.incident_started_local,
        event.reporting_year,
        event.voltage_kv,
        event.district_short_code,
        event.equipment_code,
        event.cause_code,
        event.customers_affected,
        event.customer_minutes_lost,
        event.average_minutes_off_supply,
        _json(event.quality_flags),
        event_json,
        event_sha256,
        CANONICAL_EVENT_SCHEMA_VERSION,
    )


def _reject_materialisation(
    reject: OutageReject,
    snapshot_id: str,
) -> tuple[Any, ...]:
    safe_detail = sanitise_diagnostic_value(
        {
            "error_message": reject.error_message,
            "raw_row": reject.raw_row,
        }
    )
    if safe_detail == UNSAFE_VALUE_SENTINEL:
        safe_detail = {"error_message": UNSAFE_VALUE_SENTINEL, "raw_row": {}}
    detail_json, detail_sha256 = _sha256_json(safe_detail)
    reject_id = outage_reject_id(
        snapshot_id,
        reject.row_number,
        reject.error_code,
        detail_sha256,
    )
    reject_json, reject_sha256 = _sha256_json(
        {
            "snapshot_id": snapshot_id,
            "reject_id": reject_id,
            "source_resource_id": reject.source_resource_id,
            "row_number": reject.row_number,
            "reason_code": reject.error_code,
            "safe_detail": safe_detail,
        }
    )
    del reject_json
    return (
        snapshot_id,
        reject_id,
        reject.source_resource_id,
        reject.row_number,
        reject.error_code,
        detail_json,
        reject_sha256,
    )


def _insert_or_validate_blob(
    connection: sqlite3.Connection,
    snapshot: SourceSnapshot,
) -> tuple[bool, bool]:
    row = connection.execute(
        "SELECT * FROM outage_content_blobs WHERE content_sha256 = ?",
        (snapshot.content_sha256,),
    ).fetchone()
    relative_path = snapshot.local_snapshot_path or None
    if row is None:
        connection.execute(
            """INSERT INTO outage_content_blobs (
                   content_sha256, byte_size, relative_snapshot_path, available
               ) VALUES (?, ?, ?, ?)""",
            (
                snapshot.content_sha256,
                snapshot.byte_size,
                relative_path,
                int(relative_path is not None),
            ),
        )
        return True, False
    if row["byte_size"] != snapshot.byte_size:
        raise ValueError("outage content identity conflicts with immutable byte size")
    if row["available"] == 0 and relative_path is not None:
        connection.execute(
            """UPDATE outage_content_blobs
               SET relative_snapshot_path = ?, available = 1
               WHERE content_sha256 = ?""",
            (relative_path, snapshot.content_sha256),
        )
        return False, True
    elif row["available"] == 1 and row["relative_snapshot_path"] != relative_path:
        raise ValueError("outage content identity conflicts with immutable path")
    return False, False


def _insert_or_validate_observation(
    connection: sqlite3.Connection,
    snapshot: SourceSnapshot,
) -> bool:
    values = _observation_values(snapshot)
    row = connection.execute(
        "SELECT * FROM outage_source_observations WHERE snapshot_id = ?",
        (snapshot.snapshot_id,),
    ).fetchone()
    columns = tuple(
        item[1]
        for item in connection.execute(
            "PRAGMA table_info(outage_source_observations)"
        )
    )
    if row is None:
        connection.execute(
            f"INSERT INTO outage_source_observations ({','.join(columns)}) "
            f"VALUES ({','.join('?' for _ in columns)})",
            values,
        )
        return True
    if tuple(row[column] for column in columns) != values:
        raise ValueError("source observation conflicts with immutable materialisation")
    return False


def _insert_or_validate_events(
    connection: sqlite3.Connection,
    snapshot_id: str,
    events: Sequence[OutageEvent],
    *,
    allow_initial_insert: bool,
    allow_bootstrap_completion: bool = False,
) -> None:
    expected = [_event_materialisation(event) for event in events]
    existing = connection.execute(
        """SELECT snapshot_id, event_id, source_resource_id, licence_area,
                  incident_started_local, reporting_year, voltage_kv,
                  district_short_code, equipment_code, cause_code,
                  customers_affected, customer_minutes_lost,
                  average_minutes_off_supply, quality_flags_json, event_json,
                  event_sha256, canonical_event_schema_version
           FROM outage_event_versions WHERE snapshot_id = ?
           ORDER BY event_id""",
        (snapshot_id,),
    ).fetchall()
    expected.sort(key=lambda item: item[1])
    if allow_bootstrap_completion:
        existing_by_id = {row["event_id"]: tuple(row) for row in existing}
        expected_by_id = {item[1]: item for item in expected}
        if any(
            event_id not in expected_by_id
            or expected_by_id[event_id] != existing_values
            for event_id, existing_values in existing_by_id.items()
        ):
            raise ValueError("event set conflicts with immutable materialisation")
        missing = [
            item for item in expected if item[1] not in existing_by_id
        ]
        connection.executemany(
            """INSERT INTO outage_event_versions VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            missing,
        )
        return
    if existing or not allow_initial_insert:
        if [tuple(row) for row in existing] != expected:
            raise ValueError("event set conflicts with immutable materialisation")
        return
    connection.executemany(
        """INSERT INTO outage_event_versions VALUES
           (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        expected,
    )


def _insert_or_validate_rejects(
    connection: sqlite3.Connection,
    snapshot_id: str,
    rejects: Sequence[OutageReject],
    *,
    allow_initial_insert: bool,
    allow_bootstrap_completion: bool = False,
) -> None:
    expected = [_reject_materialisation(reject, snapshot_id) for reject in rejects]
    expected.sort(key=lambda item: item[1])
    existing = connection.execute(
        """SELECT snapshot_id, reject_id, source_resource_id, row_number,
                  reason_code, safe_detail_json, reject_sha256
           FROM outage_reject_versions WHERE snapshot_id = ?
           ORDER BY reject_id""",
        (snapshot_id,),
    ).fetchall()
    if allow_bootstrap_completion:
        existing_by_id = {row["reject_id"]: tuple(row) for row in existing}
        expected_by_id = {item[1]: item for item in expected}
        if any(
            reject_id not in expected_by_id
            or expected_by_id[reject_id] != existing_values
            for reject_id, existing_values in existing_by_id.items()
        ):
            raise ValueError("reject set conflicts with immutable materialisation")
        missing = [
            item for item in expected if item[1] not in existing_by_id
        ]
        connection.executemany(
            "INSERT INTO outage_reject_versions VALUES (?, ?, ?, ?, ?, ?, ?)",
            missing,
        )
        return
    if existing or not allow_initial_insert:
        if [tuple(row) for row in existing] != expected:
            raise ValueError("reject set conflicts with immutable materialisation")
        return
    connection.executemany(
        "INSERT INTO outage_reject_versions VALUES (?, ?, ?, ?, ?, ?, ?)",
        expected,
    )


def _snapshot_from_row(row: sqlite3.Row) -> SourceSnapshot:
    return SourceSnapshot(
        snapshot_id=row["snapshot_id"],
        source_dataset_id=row["source_dataset_id"],
        package_id=row["package_id"],
        source_resource_id=row["source_resource_id"],
        licence_area=row["licence_area"],
        stable_source_url=row["stable_source_url"],
        source_modified_at=row["source_modified_at"],
        fetched_at=row["fetched_at"],
        content_sha256=row["content_sha256"],
        byte_size=row["byte_size"],
        row_count=row["row_count"],
        observed_columns=json.loads(row["observed_columns_json"]),
        licence_id=row["licence_id"],
        licence_title=row["licence_title"],
        licence_url=row["licence_url"],
        attribution=row["attribution"],
        parser_version=row["parser_version"],
        local_snapshot_path=row["relative_snapshot_path"] or "",
    )


_SNAPSHOT_SELECT = """
SELECT observation.*,
       blob.byte_size,
       blob.relative_snapshot_path,
       (
           SELECT attempt.source_modified_at
           FROM outage_fetch_attempts AS attempt
           WHERE attempt.snapshot_id = observation.snapshot_id
           ORDER BY attempt.attempted_at DESC, attempt.attempt_id DESC LIMIT 1
       ) AS source_modified_at,
       (
           SELECT attempt.attempted_at
           FROM outage_fetch_attempts AS attempt
           WHERE attempt.snapshot_id = observation.snapshot_id
           ORDER BY attempt.attempted_at DESC, attempt.attempt_id DESC LIMIT 1
       ) AS fetched_at
FROM outage_source_observations AS observation
JOIN outage_content_blobs AS blob USING (content_sha256)
"""


def save_snapshot(snapshot: SourceSnapshot, *, db_path: Path | None = None) -> int:
    """Explicit migration helper for one already-verified source observation."""
    run_migrations(_db_path(db_path))
    helper_run = f"migration-helper:{snapshot.snapshot_id}"
    with get_connection(_db_path(db_path)) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO ingestion_runs (
                   run_id, status, resources_seen, snapshots_created,
                   completed_at, warnings_json
               ) VALUES (?, 'completed', 1, 1, ?, '[]')""",
            (helper_run, _iso(snapshot.fetched_at)),
        )
        _insert_or_validate_blob(connection, snapshot)
        created = _insert_or_validate_observation(connection, snapshot)
        connection.execute(
            """INSERT OR IGNORE INTO outage_fetch_attempts VALUES
               (?, ?, ?, ?, 'completed', 200, ?, ?, ?, ?, NULL)""",
            (
                f"attempt:{uuid.uuid4().hex}",
                helper_run,
                snapshot.source_resource_id,
                _iso(snapshot.fetched_at),
                _iso(snapshot.source_modified_at),
                snapshot.snapshot_id,
                snapshot.content_sha256,
                snapshot.byte_size,
            ),
        )
    return int(created)


def list_source_snapshots(
    *,
    source_dataset_id: str | None = None,
    source_resource_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db_path: Path | None = None,
) -> list[SourceSnapshot]:
    """List immutable observations without consulting migration-6 tables."""
    _validate_limit_offset(limit, offset)
    run_migrations(_db_path(db_path))
    clauses: list[str] = []
    values: list[Any] = []
    if source_dataset_id is not None:
        clauses.append("observation.source_dataset_id = ?")
        values.append(source_dataset_id)
    if source_resource_id is not None:
        clauses.append("observation.source_resource_id = ?")
        values.append(source_resource_id)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with get_connection(_db_path(db_path)) as connection:
        rows = connection.execute(
            _SNAPSHOT_SELECT
            + where
            + " ORDER BY fetched_at DESC, observation.snapshot_id ASC LIMIT ? OFFSET ?",
            (*values, limit, offset),
        ).fetchall()
    return [_snapshot_from_row(row) for row in rows]


def count_source_snapshots(
    *,
    source_dataset_id: str | None = None,
    source_resource_id: str | None = None,
    db_path: Path | None = None,
) -> int:
    run_migrations(_db_path(db_path))
    clauses: list[str] = []
    values: list[Any] = []
    if source_dataset_id is not None:
        clauses.append("source_dataset_id = ?")
        values.append(source_dataset_id)
    if source_resource_id is not None:
        clauses.append("source_resource_id = ?")
        values.append(source_resource_id)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with get_connection(_db_path(db_path)) as connection:
        return int(connection.execute(
            "SELECT COUNT(*) FROM outage_source_observations" + where,
            values,
        ).fetchone()[0])


def source_observation_exists(
    snapshot_id: str,
    *,
    db_path: Path | None = None,
) -> bool:
    """Return whether one exact immutable source observation is registered."""
    run_migrations(_db_path(db_path))
    with get_connection(_db_path(db_path)) as connection:
        return connection.execute(
            "SELECT 1 FROM outage_source_observations WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone() is not None


def upsert_outage_events(
    events: Sequence[OutageEvent], *, db_path: Path | None = None
) -> int:
    """Insert an exact migration materialisation without permitting mutation."""
    supplied = list(events)
    events_by_snapshot: dict[str, list[OutageEvent]] = defaultdict(list)
    for event in supplied:
        events_by_snapshot[event.source_snapshot_id].append(event)
    run_migrations(_db_path(db_path))
    with get_connection(_db_path(db_path)) as connection:
        for snapshot_id, snapshot_events in events_by_snapshot.items():
            _insert_or_validate_events(
                connection,
                snapshot_id,
                snapshot_events,
                allow_initial_insert=True,
            )
    return len(supplied)


def _event_from_row(row: sqlite3.Row) -> OutageEvent:
    return OutageEvent.model_validate_json(row["event_json"])


def list_outage_event_versions(
    snapshot_ids: Sequence[str],
    *,
    limit: int = 100,
    offset: int = 0,
    db_path: Path | None = None,
    licence_area: str | None = None,
    district_short_code: str | None = None,
    reporting_year: int | None = None,
    cause_code: str | None = None,
) -> list[OutageEvent]:
    _validate_limit_offset(limit, offset)
    supplied = tuple(dict.fromkeys(snapshot_ids))
    if not supplied:
        return []
    run_migrations(_db_path(db_path))
    placeholders = ",".join("?" for _ in supplied)
    clauses = [f"snapshot_id IN ({placeholders})"]
    values: list[Any] = list(supplied)
    for name, column in _EVENT_FILTERS.items():
        value = locals()[name]
        if value is not None:
            clauses.append(f"{column} = ?")
            values.append(value)
    with get_connection(_db_path(db_path)) as connection:
        rows = connection.execute(
            "SELECT * FROM outage_event_versions WHERE "
            + " AND ".join(clauses)
            + " ORDER BY incident_started_local ASC, event_id ASC LIMIT ? OFFSET ?",
            (*values, limit, offset),
        ).fetchall()
    return [_event_from_row(row) for row in rows]


def current_outage_snapshot_ids(
    *,
    licence_area: LicenceArea | None = None,
    db_path: Path | None = None,
) -> tuple[str, ...]:
    run_migrations(_db_path(db_path))
    with get_connection(_db_path(db_path)) as connection:
        rows = connection.execute(
            """SELECT current.source_resource_id, current.snapshot_id,
                      current.run_id, observation.licence_area, run.status
               FROM current_outage_snapshots AS current
               JOIN outage_source_observations AS observation
                 ON observation.snapshot_id = current.snapshot_id
               JOIN ingestion_runs AS run ON run.run_id = current.run_id
               ORDER BY current.source_resource_id"""
        ).fetchall()
    if len(rows) != 2:
        return ()
    if tuple(row["source_resource_id"] for row in rows) != _EXPECTED_RESOURCE_IDS:
        return ()
    if len({row["run_id"] for row in rows}) != 1 or any(
        row["status"] != "completed" for row in rows
    ):
        return ()
    selected = [
        row["snapshot_id"]
        for row in rows
        if licence_area is None or row["licence_area"] == licence_area
    ]
    return tuple(selected)


def resolve_outage_evidence_scope(
    *,
    source_snapshot_ids: Sequence[str] | None = None,
    licence_area: LicenceArea | None = None,
    db_path: Path | None = None,
) -> OutageEvidenceScopeV1:
    if source_snapshot_ids is None:
        snapshot_ids = current_outage_snapshot_ids(
            licence_area=licence_area, db_path=db_path
        )
        if not snapshot_ids:
            raise ValueError("current atomic outage evidence set is unavailable")
        resolution = "current_atomic_set"
    else:
        snapshot_ids = tuple(source_snapshot_ids)
        if not snapshot_ids or len(set(snapshot_ids)) != len(snapshot_ids):
            raise ValueError("explicit snapshot set must be non-empty and unique")
        resolution = "explicit_snapshot_set"
    run_migrations(_db_path(db_path))
    placeholders = ",".join("?" for _ in snapshot_ids)
    with get_connection(_db_path(db_path)) as connection:
        rows = connection.execute(
            f"""SELECT snapshot_id, source_resource_id, licence_area
                FROM outage_source_observations
                WHERE snapshot_id IN ({placeholders})""",
            snapshot_ids,
        ).fetchall()
    if len(rows) != len(snapshot_ids):
        raise ValueError("snapshot evidence set contains an unknown snapshot")
    resource_ids = tuple(sorted(row["source_resource_id"] for row in rows))
    if licence_area is None and resource_ids != _EXPECTED_RESOURCE_IDS:
        raise ValueError("snapshot evidence set is not the exact two-resource set")
    if licence_area is not None and any(
        row["licence_area"] != licence_area for row in rows
    ):
        raise ValueError("snapshot evidence set does not match licence area")
    ordered_ids = tuple(
        row["snapshot_id"]
        for row in sorted(rows, key=lambda item: item["source_resource_id"])
    )
    return OutageEvidenceScopeV1(
        snapshot_ids=ordered_ids,
        source_resource_ids=resource_ids,
        resolution=resolution,
    )


def _query_snapshot_ids(
    source_snapshot_ids: Sequence[str] | None,
    db_path: Path | None,
) -> tuple[str, ...]:
    if source_snapshot_ids is not None:
        supplied = tuple(dict.fromkeys(source_snapshot_ids))
        if not supplied:
            raise ValueError("explicit outage snapshot set must be non-empty")
        return supplied
    current = current_outage_snapshot_ids(db_path=db_path)
    if not current:
        raise ValueError("current atomic outage evidence set is unavailable")
    return current


def list_outage_events(
    *,
    source_snapshot_ids: Sequence[str] | None = None,
    licence_area: str | None = None,
    district_short_code: str | None = None,
    reporting_year: int | None = None,
    cause_code: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db_path: Path | None = None,
) -> list[OutageEvent]:
    """List current or explicitly selected immutable event versions."""
    _validate_limit_offset(limit, offset)
    run_migrations(_db_path(db_path))
    return list_outage_event_versions(
        _query_snapshot_ids(source_snapshot_ids, db_path),
        licence_area=licence_area,
        district_short_code=district_short_code,
        reporting_year=reporting_year,
        cause_code=cause_code,
        limit=limit,
        offset=offset,
        db_path=db_path,
    )


def count_outage_events(
    *,
    source_snapshot_ids: Sequence[str] | None = None,
    licence_area: str | None = None,
    district_short_code: str | None = None,
    reporting_year: int | None = None,
    cause_code: str | None = None,
    db_path: Path | None = None,
) -> int:
    run_migrations(_db_path(db_path))
    snapshot_ids = _query_snapshot_ids(source_snapshot_ids, db_path)
    placeholders = ",".join("?" for _ in snapshot_ids)
    clauses = [f"snapshot_id IN ({placeholders})"]
    values: list[Any] = list(snapshot_ids)
    filters = {
        "licence_area": licence_area,
        "district_short_code": district_short_code,
        "reporting_year": reporting_year,
        "cause_code": cause_code,
    }
    for name, column in _EVENT_FILTERS.items():
        if filters[name] is not None:
            clauses.append(f"{column} = ?")
            values.append(filters[name])
    with get_connection(_db_path(db_path)) as connection:
        return int(connection.execute(
            "SELECT COUNT(*) FROM outage_event_versions WHERE "
            + " AND ".join(clauses),
            values,
        ).fetchone()[0])


def get_outage_event(
    event_id: str,
    db_path: Path | None = None,
    *,
    source_snapshot_ids: Sequence[str] | None = None,
) -> OutageEvent | None:
    run_migrations(_db_path(db_path))
    snapshot_ids = _query_snapshot_ids(source_snapshot_ids, db_path)
    placeholders = ",".join("?" for _ in snapshot_ids)
    with get_connection(_db_path(db_path)) as connection:
        row = connection.execute(
            f"""SELECT * FROM outage_event_versions
                WHERE snapshot_id IN ({placeholders}) AND event_id = ?
                ORDER BY snapshot_id LIMIT 1""",
            (*snapshot_ids, event_id),
        ).fetchone()
    return _event_from_row(row) if row is not None else None


def summarise_outage_events(
    *,
    source_snapshot_ids: Sequence[str] | None = None,
    licence_area: str | None = None,
    reporting_year: int | None = None,
    db_path: Path | None = None,
) -> OutageSummary:
    run_migrations(_db_path(db_path))
    snapshot_ids = _query_snapshot_ids(source_snapshot_ids, db_path)
    placeholders = ",".join("?" for _ in snapshot_ids)
    clauses = [f"snapshot_id IN ({placeholders})"]
    values: list[Any] = list(snapshot_ids)
    if licence_area is not None:
        clauses.append("licence_area = ?")
        values.append(licence_area)
    if reporting_year is not None:
        clauses.append("reporting_year = ?")
        values.append(reporting_year)
    with get_connection(_db_path(db_path)) as connection:
        row = connection.execute(
            """SELECT COUNT(*) AS event_count,
                      SUM(customers_affected) AS customers_affected_total,
                      SUM(customer_minutes_lost) AS customer_minutes_lost_total,
                      MIN(incident_started_local) AS incident_started_local_min,
                      MAX(incident_started_local) AS incident_started_local_max
               FROM outage_event_versions WHERE """
            + " AND ".join(clauses),
            values,
        ).fetchone()
    return OutageSummary(**dict(row))


def save_outage_rejects(
    rejects: Sequence[OutageReject], *, db_path: Path | None = None
) -> int:
    """Legacy diagnostic helper retained only for migration compatibility."""
    supplied = list(rejects)
    run_migrations(_db_path(db_path))
    with get_connection(_db_path(db_path)) as connection:
        connection.executemany(
            """INSERT INTO outage_rejects (
                   run_id, source_resource_id, row_number, error_code,
                   error_message, raw_row_json
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (
                    item.run_id,
                    item.source_resource_id,
                    item.row_number,
                    item.error_code,
                    str(sanitise_diagnostic_value(item.error_message)),
                    _json(sanitise_diagnostic_value(item.raw_row)),
                )
                for item in supplied
            ],
        )
    return len(supplied)


def _invalid_completed_run() -> ValueError:
    return ValueError("completed ingestion requires one exact completed run")


def _validate_completed_run_payload(
    *,
    run_id: str,
    resources_seen: int,
    snapshots: Sequence[SourceSnapshot],
    events: Sequence[OutageEvent],
    rejects: Sequence[OutageReject],
    fetch_attempts: Sequence[OutageFetchAttemptPublicV1],
) -> None:
    if (
        not run_id
        or resources_seen != 2
        or len(snapshots) != 2
        or len(fetch_attempts) != 2
    ):
        raise _invalid_completed_run()

    snapshot_by_resource: dict[str, SourceSnapshot] = {}
    snapshot_ids: set[str] = set()
    for snapshot in snapshots:
        if (
            snapshot.source_resource_id not in _EXPECTED_RESOURCE_IDS
            or snapshot.source_resource_id in snapshot_by_resource
            or snapshot.snapshot_id in snapshot_ids
            or snapshot.snapshot_id
            != (
                f"ssen-nafirs-hv:{snapshot.source_resource_id}:"
                f"sha256:{snapshot.content_sha256}"
            )
        ):
            raise _invalid_completed_run()
        snapshot_by_resource[snapshot.source_resource_id] = snapshot
        snapshot_ids.add(snapshot.snapshot_id)
    if tuple(sorted(snapshot_by_resource)) != _EXPECTED_RESOURCE_IDS:
        raise _invalid_completed_run()

    attempt_by_resource: dict[str, OutageFetchAttemptPublicV1] = {}
    attempt_ids: set[str] = set()
    for attempt in fetch_attempts:
        snapshot = snapshot_by_resource.get(attempt.source_resource_id)
        if (
            snapshot is None
            or attempt.source_resource_id in attempt_by_resource
            or attempt.attempt_id in attempt_ids
            or attempt.run_id != run_id
            or attempt.status != "completed"
            or attempt.response_status != 200
            or attempt.error_code is not None
            or attempt.source_snapshot_id != snapshot.snapshot_id
            or attempt.content_sha256 != snapshot.content_sha256
            or attempt.byte_size != snapshot.byte_size
            or attempt.attempted_at != snapshot.fetched_at
            or attempt.source_modified_at != snapshot.source_modified_at
        ):
            raise _invalid_completed_run()
        attempt_by_resource[attempt.source_resource_id] = attempt
        attempt_ids.add(attempt.attempt_id)
    if tuple(sorted(attempt_by_resource)) != _EXPECTED_RESOURCE_IDS:
        raise _invalid_completed_run()

    materialised_rows = dict.fromkeys(snapshot_ids, 0)
    event_keys: set[tuple[str, str]] = set()
    for event in events:
        snapshot = next(
            (
                item
                for item in snapshots
                if item.snapshot_id == event.source_snapshot_id
            ),
            None,
        )
        event_key = (event.source_snapshot_id, event.event_id)
        if (
            snapshot is None
            or event_key in event_keys
            or event.source_resource_id != snapshot.source_resource_id
            or event.source_dataset_id != snapshot.source_dataset_id
            or event.licence_area != snapshot.licence_area
        ):
            raise _invalid_completed_run()
        event_keys.add(event_key)
        materialised_rows[snapshot.snapshot_id] += 1
    reject_keys: set[tuple[str, int]] = set()
    for reject in rejects:
        snapshot = snapshot_by_resource.get(reject.source_resource_id)
        reject_key = (reject.source_resource_id, reject.row_number)
        if (
            snapshot is None
            or reject.run_id != run_id
            or reject.row_number < 1
            or reject_key in reject_keys
        ):
            raise _invalid_completed_run()
        reject_keys.add(reject_key)
        materialised_rows[snapshot.snapshot_id] += 1
    if any(
        snapshot.row_count != materialised_rows[snapshot.snapshot_id]
        for snapshot in snapshots
    ):
        raise _invalid_completed_run()


def commit_ingestion_run(
    *,
    run_id: str,
    resources_seen: int,
    snapshots: Sequence[SourceSnapshot],
    events: Sequence[OutageEvent],
    rejects: Sequence[OutageReject],
    warnings: Sequence[str],
    fetch_attempts: Sequence[OutageFetchAttemptPublicV1] = (),
    db_path: Path | None = None,
) -> SyncResult:
    """Atomically persist a completed immutable materialisation and current set."""
    supplied_snapshots = list(snapshots)
    supplied_events = list(events)
    supplied_rejects = list(rejects)
    attempts = list(fetch_attempts)
    _validate_completed_run_payload(
        run_id=run_id,
        resources_seen=resources_seen,
        snapshots=supplied_snapshots,
        events=supplied_events,
        rejects=supplied_rejects,
        fetch_attempts=attempts,
    )
    run_migrations(_db_path(db_path))
    safe_warnings = sanitise_diagnostic_value(list(warnings))
    if safe_warnings == UNSAFE_VALUE_SENTINEL:
        safe_warnings = [UNSAFE_VALUE_SENTINEL]
    safe_warning_strings = [str(item) for item in safe_warnings]
    events_by_snapshot: dict[str, list[OutageEvent]] = defaultdict(list)
    supplied_snapshot_ids = {item.snapshot_id for item in supplied_snapshots}
    for event in supplied_events:
        if event.source_snapshot_id not in supplied_snapshot_ids:
            raise sqlite3.IntegrityError(
                "outage event has no supplied source observation"
            )
        events_by_snapshot[event.source_snapshot_id].append(event)
    snapshot_by_resource = {
        item.source_resource_id: item.snapshot_id for item in supplied_snapshots
    }
    rejects_by_snapshot: dict[str, list[OutageReject]] = defaultdict(list)
    for reject in supplied_rejects:
        snapshot_id = snapshot_by_resource.get(reject.source_resource_id)
        if snapshot_id is None:
            raise ValueError("reject has no supplied source observation")
        rejects_by_snapshot[snapshot_id].append(reject)
    with get_connection(_db_path(db_path)) as connection:
        snapshots_created = 0
        connection.execute(
            """INSERT INTO ingestion_runs (
                   run_id, status, resources_seen, warnings_json
               ) VALUES (?, 'running', ?, ?)""",
            (run_id, resources_seen, _json(safe_warning_strings)),
        )
        for snapshot in supplied_snapshots:
            _, bootstrap_completion = _insert_or_validate_blob(
                connection, snapshot
            )
            observation_created = _insert_or_validate_observation(
                connection, snapshot
            )
            snapshots_created += int(observation_created)
            _insert_or_validate_events(
                connection,
                snapshot.snapshot_id,
                events_by_snapshot[snapshot.snapshot_id],
                allow_initial_insert=observation_created,
                allow_bootstrap_completion=bootstrap_completion,
            )
            _insert_or_validate_rejects(
                connection,
                snapshot.snapshot_id,
                rejects_by_snapshot[snapshot.snapshot_id],
                allow_initial_insert=observation_created,
                allow_bootstrap_completion=bootstrap_completion,
            )
            connection.execute(
                "INSERT INTO ingestion_run_snapshots VALUES (?, ?)",
                (run_id, snapshot.snapshot_id),
            )
        for attempt in attempts:
            connection.execute(
                """INSERT INTO outage_fetch_attempts VALUES
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    attempt.attempt_id,
                    attempt.run_id,
                    attempt.source_resource_id,
                    _iso(attempt.attempted_at),
                    attempt.status,
                    attempt.response_status,
                    _iso(attempt.source_modified_at),
                    attempt.source_snapshot_id,
                    attempt.content_sha256,
                    attempt.byte_size,
                    attempt.error_code,
                ),
            )
        if tuple(sorted(snapshot_by_resource)) == _EXPECTED_RESOURCE_IDS:
            updated_at = _iso(max(item.attempted_at for item in attempts))
            for resource_id in _EXPECTED_RESOURCE_IDS:
                connection.execute(
                    """INSERT INTO current_outage_snapshots VALUES (?, ?, ?, ?)
                       ON CONFLICT(source_resource_id) DO UPDATE SET
                           snapshot_id=excluded.snapshot_id,
                           run_id=excluded.run_id,
                           updated_at=excluded.updated_at""",
                    (resource_id, snapshot_by_resource[resource_id], run_id, updated_at),
                )
        snapshots_reused = len(supplied_snapshots) - snapshots_created
        connection.execute(
            """UPDATE ingestion_runs SET
                   status='completed', snapshots_created=?, snapshots_reused=?,
                   events_written=?, rejects_written=?, completed_at=?
               WHERE run_id=?""",
            (
                snapshots_created,
                snapshots_reused,
                len(supplied_events),
                len(supplied_rejects),
                _iso(max(item.attempted_at for item in attempts)),
                run_id,
            ),
        )
    return SyncResult(
        run_id=run_id,
        status="completed",
        resources_seen=resources_seen,
        snapshots_created=snapshots_created,
        snapshots_reused=snapshots_reused,
        events_written=len(supplied_events),
        rejects_written=len(supplied_rejects),
        warnings=safe_warning_strings,
    )


def record_failed_ingestion_run(
    *,
    run_id: str,
    resources_seen: int,
    error: Exception,
    warnings: Sequence[Any] = (),
    fetch_attempts: Sequence[OutageFetchAttemptPublicV1] = (),
    db_path: Path | None = None,
) -> SyncResult:
    """Record one sanitised failed run and its safe attempted-resource evidence."""
    safe_warnings = sanitise_diagnostic_value(list(warnings))
    if safe_warnings == UNSAFE_VALUE_SENTINEL:
        safe_warnings = [UNSAFE_VALUE_SENTINEL]
    safe_warning_strings = [
        item if isinstance(item, str) else _json(item) for item in safe_warnings
    ]
    safe_failure = str(sanitise_diagnostic_value(safe_error(error)))
    attempts = list(fetch_attempts)
    completed_at = max(
        (item.attempted_at for item in attempts),
        default=datetime.now(timezone.utc),
    )
    run_migrations(_db_path(db_path))
    with get_connection(_db_path(db_path)) as connection:
        connection.execute(
            """INSERT INTO ingestion_runs (
                   run_id, status, resources_seen, warnings_json, error,
                   completed_at
               ) VALUES (?, 'failed', ?, ?, ?, ?)
               ON CONFLICT(run_id) DO UPDATE SET
                   status='failed', resources_seen=excluded.resources_seen,
                   snapshots_created=0, snapshots_reused=0, events_written=0,
                   rejects_written=0, warnings_json=excluded.warnings_json,
                   error=excluded.error, completed_at=excluded.completed_at""",
            (
                run_id,
                resources_seen,
                _json(safe_warnings),
                safe_failure,
                _iso(completed_at),
            ),
        )
        for attempt in attempts:
            snapshot_id = attempt.source_snapshot_id
            if snapshot_id is not None:
                exists = connection.execute(
                    "SELECT 1 FROM outage_source_observations WHERE snapshot_id=?",
                    (snapshot_id,),
                ).fetchone()
                if exists is None:
                    snapshot_id = None
            connection.execute(
                """INSERT OR REPLACE INTO outage_fetch_attempts VALUES
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    attempt.attempt_id,
                    run_id,
                    attempt.source_resource_id,
                    _iso(attempt.attempted_at),
                    attempt.status,
                    attempt.response_status,
                    _iso(attempt.source_modified_at),
                    snapshot_id,
                    attempt.content_sha256,
                    attempt.byte_size,
                    attempt.error_code,
                ),
            )
    return SyncResult(
        run_id=run_id,
        status="failed",
        resources_seen=resources_seen,
        snapshots_created=0,
        snapshots_reused=0,
        events_written=0,
        rejects_written=0,
        warnings=safe_warning_strings,
    )


def list_ingestion_run_snapshots(
    run_id: str, *, db_path: Path | None = None
) -> list[SourceSnapshot]:
    run_migrations(_db_path(db_path))
    with get_connection(_db_path(db_path)) as connection:
        rows = connection.execute(
            _SNAPSHOT_SELECT
            + " JOIN ingestion_run_snapshots AS association "
            "ON association.snapshot_id = observation.snapshot_id "
            "WHERE association.run_id = ? "
            "ORDER BY observation.source_resource_id",
            (run_id,),
        ).fetchall()
    return [_snapshot_from_row(row) for row in rows]


def build_ssen_fetch_manifest(
    run_id: str, *, db_path: Path | None = None
) -> SsenFetchManifestV1:
    run_migrations(_db_path(db_path))
    with get_connection(_db_path(db_path)) as connection:
        rows = connection.execute(
            """SELECT * FROM outage_fetch_attempts
               WHERE run_id=? ORDER BY source_resource_id, attempt_id""",
            (run_id,),
        ).fetchall()
    if not rows:
        raise ValueError("ingestion run has no fetch attempts")
    attempts = tuple(
        OutageFetchAttemptPublicV1(
            attempt_id=row["attempt_id"],
            run_id=row["run_id"],
            source_resource_id=row["source_resource_id"],
            attempted_at=row["attempted_at"],
            status=row["status"],
            response_status=row["response_status"],
            source_modified_at=row["source_modified_at"],
            source_snapshot_id=row["snapshot_id"],
            content_sha256=row["content_sha256"],
            byte_size=row["byte_size"],
            error_code=row["error_code"],
        )
        for row in rows
    )
    return SsenFetchManifestV1(
        run_id=run_id,
        source_contract_version="ssen-nafirs-hv-v1",
        attempted_at=min(item.attempted_at for item in attempts),
        attempts=attempts,
    )

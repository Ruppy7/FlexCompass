"""SQLite persistence and deterministic queries for outage evidence."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from app.catalogue_sync import redact, safe_error
from app.db import get_connection, run_migrations
from app.outages import (
    OutageEvent,
    OutageReject,
    OutageSummary,
    SourceSnapshot,
    SyncResult,
)

_EVENT_FIELDS = tuple(OutageEvent.model_fields)
_EVENT_COLUMNS = tuple(
    "quality_flags_json"
    if field == "quality_flags"
    else "raw_record_json"
    if field == "raw_record"
    else field
    for field in _EVENT_FIELDS
)
_EVENT_FILTERS = {
    "licence_area": "licence_area",
    "district_short_code": "district_short_code",
    "reporting_year": "reporting_year",
    "cause_code": "cause_code",
}
_SNAPSHOT_FILTERS = {
    "source_dataset_id": "source_dataset_id",
    "source_resource_id": "source_resource_id",
}
_R2_SIGNED_TARGET = re.compile(
    r"https://83025b28472d6aa2bf5ae59f3724aa78"
    r"\.r2\.cloudflarestorage\.com(?::443)?"
    r"(?=/|[?#\s\"'<>]|$)(?:/[^\s\"'<>]*)?",
    re.IGNORECASE,
)
_X_AMZ_FIELD = re.compile(
    r"x-amz-[a-z0-9-]+(?:\s*[:=]\s*[^&,\s}\])\"']+)?",
    re.IGNORECASE,
)
_PERSISTENCE_DECODE_ROUNDS = 3


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _decoded_layers(value: str) -> list[str]:
    """Decode only for detection, with the Package 1 three-round budget."""
    layers = [value]
    decoded = value
    for _ in range(_PERSISTENCE_DECODE_ROUNDS):
        further_decoded = unquote(decoded)
        if further_decoded == decoded:
            break
        layers.append(further_decoded)
        decoded = further_decoded
    return layers


def _has_signed_contamination(value: str, *, key: bool = False) -> bool:
    layers = _decoded_layers(value)
    return any(
        _R2_SIGNED_TARGET.search(layer) or _X_AMZ_FIELD.search(layer)
        for layer in layers
    ) or (
        key
        and any(
            layer.strip().casefold() in {"signed_url", "redirect_url"}
            for layer in layers
        )
    )


def _safe_failure_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        safe_mapping: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _has_signed_contamination(key_text, key=True):
                continue
            safe_mapping[key_text] = _safe_failure_value(item)
        return redact(safe_mapping)
    if isinstance(value, (list, tuple)):
        return [_safe_failure_value(item) for item in value]
    if isinstance(value, str):
        if _has_signed_contamination(value):
            return "[REDACTED SIGNED REDIRECT]"
        return redact(value)
    return redact(value)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _validate_limit_offset(limit: int, offset: int) -> None:
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if offset < 0:
        raise ValueError("offset must be non-negative")


def _where(
    allowed: Mapping[str, str],
    supplied: Mapping[str, Any],
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    for name, column in allowed.items():
        value = supplied.get(name)
        if value is not None:
            clauses.append(f"{column} = ?")
            values.append(value)
    return (" WHERE " + " AND ".join(clauses) if clauses else "", values)


def _validate_stable_source_url(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "data-api.ssen.co.uk"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("snapshot provenance requires a stable SSEN source URL")


def _snapshot_values(snapshot: SourceSnapshot) -> tuple[Any, ...]:
    _validate_stable_source_url(snapshot.stable_source_url)
    return (
        snapshot.snapshot_id,
        snapshot.source_dataset_id,
        snapshot.package_id,
        snapshot.source_resource_id,
        snapshot.licence_area,
        snapshot.stable_source_url,
        _iso(snapshot.source_modified_at),
        _iso(snapshot.fetched_at),
        snapshot.content_sha256,
        snapshot.byte_size,
        snapshot.row_count,
        _json(snapshot.observed_columns),
        snapshot.licence_id,
        snapshot.licence_title,
        snapshot.licence_url,
        snapshot.attribution,
        snapshot.parser_version,
        snapshot.local_snapshot_path,
    )


def _save_snapshot(
    connection: sqlite3.Connection,
    snapshot: SourceSnapshot,
) -> int:
    connection.execute(
        """
        INSERT INTO source_snapshots (
            snapshot_id, source_dataset_id, package_id, source_resource_id,
            licence_area, stable_source_url, source_modified_at, fetched_at,
            content_sha256, byte_size, row_count, observed_columns_json,
            licence_id, licence_title, licence_url, attribution, parser_version,
            local_snapshot_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(snapshot_id) DO UPDATE SET
            source_dataset_id = excluded.source_dataset_id,
            package_id = excluded.package_id,
            source_resource_id = excluded.source_resource_id,
            licence_area = excluded.licence_area,
            stable_source_url = excluded.stable_source_url,
            source_modified_at = excluded.source_modified_at,
            fetched_at = excluded.fetched_at,
            content_sha256 = excluded.content_sha256,
            byte_size = excluded.byte_size,
            row_count = excluded.row_count,
            observed_columns_json = excluded.observed_columns_json,
            licence_id = excluded.licence_id,
            licence_title = excluded.licence_title,
            licence_url = excluded.licence_url,
            attribution = excluded.attribution,
            parser_version = excluded.parser_version,
            local_snapshot_path = excluded.local_snapshot_path
        """,
        _snapshot_values(snapshot),
    )
    return 1


def save_snapshot(
    snapshot: SourceSnapshot,
    *,
    db_path: Path | None = None,
) -> int:
    """Persist one source manifest using only its stable SSEN origin URL."""
    run_migrations(db_path)
    with get_connection(db_path) as connection:
        return _save_snapshot(connection, snapshot)


def _snapshot_from_row(row: sqlite3.Row) -> SourceSnapshot:
    values = dict(row)
    values["observed_columns"] = json.loads(values.pop("observed_columns_json"))
    return SourceSnapshot(**values)


def list_source_snapshots(
    *,
    source_dataset_id: str | None = None,
    source_resource_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db_path: Path | None = None,
) -> list[SourceSnapshot]:
    """List snapshot manifests in stable newest-first order."""
    _validate_limit_offset(limit, offset)
    run_migrations(db_path)
    where, values = _where(
        _SNAPSHOT_FILTERS,
        {
            "source_dataset_id": source_dataset_id,
            "source_resource_id": source_resource_id,
        },
    )
    with get_connection(db_path) as connection:
        rows = connection.execute(
            f"""SELECT * FROM source_snapshots{where}
                ORDER BY fetched_at DESC, snapshot_id ASC
                LIMIT ? OFFSET ?""",
            (*values, limit, offset),
        ).fetchall()
    return [_snapshot_from_row(row) for row in rows]


def count_source_snapshots(
    *,
    source_dataset_id: str | None = None,
    source_resource_id: str | None = None,
    db_path: Path | None = None,
) -> int:
    """Count snapshots using the exact list-query filters."""
    run_migrations(db_path)
    where, values = _where(
        _SNAPSHOT_FILTERS,
        {
            "source_dataset_id": source_dataset_id,
            "source_resource_id": source_resource_id,
        },
    )
    with get_connection(db_path) as connection:
        return int(
            connection.execute(
                f"SELECT COUNT(*) FROM source_snapshots{where}",
                values,
            ).fetchone()[0]
        )


def _event_values(event: OutageEvent) -> tuple[Any, ...]:
    values = event.model_dump()
    values["quality_flags"] = _json(values["quality_flags"])
    values["raw_record"] = _json(values["raw_record"])
    return tuple(values[field] for field in _EVENT_FIELDS)


def _upsert_outage_events(
    connection: sqlite3.Connection,
    events: Sequence[OutageEvent],
) -> int:
    if not events:
        return 0
    placeholders = ", ".join("?" for _ in _EVENT_COLUMNS)
    assignments = ", ".join(
        f"{column} = excluded.{column}"
        for column in _EVENT_COLUMNS
        if column != "event_id"
    )
    connection.executemany(
        f"""INSERT INTO outage_events ({", ".join(_EVENT_COLUMNS)})
            VALUES ({placeholders})
            ON CONFLICT(event_id) DO UPDATE SET {assignments}""",
        [_event_values(event) for event in events],
    )
    return len(events)


def upsert_outage_events(
    events: Sequence[OutageEvent],
    *,
    db_path: Path | None = None,
) -> int:
    """Insert or replace the evidence attached to supplied event identities."""
    supplied = list(events)
    run_migrations(db_path)
    with get_connection(db_path) as connection:
        return _upsert_outage_events(connection, supplied)


def _event_from_row(row: sqlite3.Row) -> OutageEvent:
    values = dict(row)
    values["quality_flags"] = json.loads(values.pop("quality_flags_json"))
    values["raw_record"] = json.loads(values.pop("raw_record_json"))
    return OutageEvent(**values)


def _event_where(
    *,
    licence_area: str | None,
    district_short_code: str | None,
    reporting_year: int | None,
    cause_code: str | None,
) -> tuple[str, list[Any]]:
    return _where(
        _EVENT_FILTERS,
        {
            "licence_area": licence_area,
            "district_short_code": district_short_code,
            "reporting_year": reporting_year,
            "cause_code": cause_code,
        },
    )


def list_outage_events(
    *,
    licence_area: str | None = None,
    district_short_code: str | None = None,
    reporting_year: int | None = None,
    cause_code: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db_path: Path | None = None,
) -> list[OutageEvent]:
    """List outage evidence using allow-listed filters and stable ordering."""
    _validate_limit_offset(limit, offset)
    run_migrations(db_path)
    where, values = _event_where(
        licence_area=licence_area,
        district_short_code=district_short_code,
        reporting_year=reporting_year,
        cause_code=cause_code,
    )
    with get_connection(db_path) as connection:
        rows = connection.execute(
            f"""SELECT * FROM outage_events{where}
                ORDER BY incident_started_local ASC, event_id ASC
                LIMIT ? OFFSET ?""",
            (*values, limit, offset),
        ).fetchall()
    return [_event_from_row(row) for row in rows]


def count_outage_events(
    *,
    licence_area: str | None = None,
    district_short_code: str | None = None,
    reporting_year: int | None = None,
    cause_code: str | None = None,
    db_path: Path | None = None,
) -> int:
    """Count outage evidence using the exact list-query filters."""
    run_migrations(db_path)
    where, values = _event_where(
        licence_area=licence_area,
        district_short_code=district_short_code,
        reporting_year=reporting_year,
        cause_code=cause_code,
    )
    with get_connection(db_path) as connection:
        return int(
            connection.execute(
                f"SELECT COUNT(*) FROM outage_events{where}",
                values,
            ).fetchone()[0]
        )


def get_outage_event(
    event_id: str,
    db_path: Path | None = None,
) -> OutageEvent | None:
    """Return one outage event by its canonical identity."""
    run_migrations(db_path)
    with get_connection(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM outage_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    return _event_from_row(row) if row is not None else None


def summarise_outage_events(
    *,
    licence_area: str | None = None,
    reporting_year: int | None = None,
    db_path: Path | None = None,
) -> OutageSummary:
    """Aggregate explicitly filtered evidence without filling unknown totals."""
    run_migrations(db_path)
    where, values = _where(
        {
            "licence_area": "licence_area",
            "reporting_year": "reporting_year",
        },
        {
            "licence_area": licence_area,
            "reporting_year": reporting_year,
        },
    )
    with get_connection(db_path) as connection:
        row = connection.execute(
            f"""SELECT
                    COUNT(*) AS event_count,
                    SUM(customers_affected) AS customers_affected_total,
                    SUM(customer_minutes_lost) AS customer_minutes_lost_total,
                    MIN(incident_started_local) AS incident_started_local_min,
                    MAX(incident_started_local) AS incident_started_local_max
                FROM outage_events{where}""",
            values,
        ).fetchone()
    return OutageSummary(**dict(row))


def _save_outage_rejects(
    connection: sqlite3.Connection,
    rejects: Sequence[OutageReject],
) -> int:
    connection.executemany(
        """INSERT INTO outage_rejects (
               run_id, source_resource_id, row_number, error_code,
               error_message, raw_row_json
           ) VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (
                reject.run_id,
                reject.source_resource_id,
                reject.row_number,
                reject.error_code,
                str(_safe_failure_value(reject.error_message)),
                _json(_safe_failure_value(reject.raw_row)),
            )
            for reject in rejects
        ],
    )
    return len(rejects)


def save_outage_rejects(
    rejects: Sequence[OutageReject],
    *,
    db_path: Path | None = None,
) -> int:
    """Persist redacted rejects outside the sync entry point when required."""
    supplied = list(rejects)
    run_migrations(db_path)
    with get_connection(db_path) as connection:
        return _save_outage_rejects(connection, supplied)


def commit_ingestion_run(
    *,
    run_id: str,
    resources_seen: int,
    snapshots: Sequence[SourceSnapshot],
    events: Sequence[OutageEvent],
    rejects: Sequence[OutageReject],
    snapshots_created: int,
    snapshots_reused: int,
    warnings: Sequence[str],
    db_path: Path | None = None,
) -> SyncResult:
    """Atomically persist one completed ingestion run and all of its evidence."""
    supplied_snapshots = list(snapshots)
    supplied_events = list(events)
    supplied_rejects = list(rejects)
    safe_warnings = [
        str(item) for item in _safe_failure_value(list(warnings))
    ]
    run_migrations(db_path)
    with get_connection(db_path) as connection:
        connection.execute(
            """INSERT INTO ingestion_runs (
                   run_id, status, resources_seen, warnings_json
               ) VALUES (?, 'running', ?, ?)""",
            (run_id, resources_seen, _json(safe_warnings)),
        )
        for snapshot in supplied_snapshots:
            _save_snapshot(connection, snapshot)
        events_written = _upsert_outage_events(connection, supplied_events)
        rejects_written = _save_outage_rejects(connection, supplied_rejects)
        connection.execute(
            """UPDATE ingestion_runs SET
                   status = 'completed',
                   snapshots_created = ?,
                   snapshots_reused = ?,
                   events_written = ?,
                   rejects_written = ?,
                   completed_at = datetime('now')
               WHERE run_id = ?""",
            (
                snapshots_created,
                snapshots_reused,
                events_written,
                rejects_written,
                run_id,
            ),
        )
    return SyncResult(
        run_id=run_id,
        status="completed",
        resources_seen=resources_seen,
        snapshots_created=snapshots_created,
        snapshots_reused=snapshots_reused,
        events_written=events_written,
        rejects_written=rejects_written,
        warnings=safe_warnings,
    )


def record_failed_ingestion_run(
    *,
    run_id: str,
    resources_seen: int,
    error: Exception,
    warnings: Sequence[Any] = (),
    db_path: Path | None = None,
) -> SyncResult:
    """Record only redacted failure state in a separate short transaction."""
    safe_warnings = _safe_failure_value(list(warnings))
    safe_warning_strings = [
        item if isinstance(item, str) else _json(item) for item in safe_warnings
    ]
    safe_failure = safe_error(error)
    run_migrations(db_path)
    with get_connection(db_path) as connection:
        connection.execute(
            """INSERT INTO ingestion_runs (
                   run_id, status, resources_seen, warnings_json, error,
                   completed_at
               ) VALUES (?, 'failed', ?, ?, ?, datetime('now'))
               ON CONFLICT(run_id) DO UPDATE SET
                   status = 'failed',
                   resources_seen = excluded.resources_seen,
                   snapshots_created = 0,
                   snapshots_reused = 0,
                   events_written = 0,
                   rejects_written = 0,
                   warnings_json = excluded.warnings_json,
                   error = excluded.error,
                   completed_at = excluded.completed_at""",
            (
                run_id,
                resources_seen,
                _json(safe_warnings),
                safe_failure,
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

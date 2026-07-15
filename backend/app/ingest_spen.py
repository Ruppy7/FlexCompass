"""SPEN (Scottish & Southern Electricity Networks) data ingest pipeline.

Fetches flexibility data from the SPEN OpenDataSoft portal, discovers schemas
dynamically, and stores normalised records into SQLite.

Datasets:
  - flexibility_competitions  (spen_competitions)
  - flexibility_bids          (spen_bids)
  - flexibility-dispatch      (spen_dispatch)
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Load .env from the project root
_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_ENV_PATH)

BASE_URL = "https://spenergynetworks.opendatasoft.com/api/v2/catalog/datasets"
BATCH_SIZE = 1000
REQUEST_TIMEOUT = 120  # seconds per HTTP request

# Dataset IDs on the portal (used as URL path segments)
DATASETS: dict[str, str] = {
    "spen_competitions": "flexibility_competitions",
    "spen_bids": "flexibility_bids",
    "spen_dispatch": "flexibility-dispatch",
}

# Sort fields for keyset pagination (ODS caps offset+limit at 10 000).
# Each dataset needs a field to sort by so we can use  WHERE field > last_val
# to page past the 10 k ceiling.
# Set to None to use a single-pass full export (limit=-1) instead.
SORT_KEYS: dict[str, str | None] = {
    "spen_competitions": "service_period_start_date",
    "spen_bids": "start_date",
    "spen_dispatch": None,  # no usable sortable field → single-pass export
}

# Normalised field mappings for flexibility_competitions
COMPETITION_FIELD_MAP: dict[str, str] = {
    "zone": "constraint_management_zone",
    "direction": "demand_or_generation_turn_up_down",
    "price": "guide_price_budget_additional_information",
    "capacity_mw": "capacity_required_mw",
    "product": "product_type",
    "market": "market_competition_name",
}

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get_token() -> str:
    token = os.getenv("SPEN_DATAPORTAL_TOKEN")
    if not token:
        raise RuntimeError(
            "SPEN_DATAPORTAL_TOKEN not set. "
            f"Ensure it exists in {_ENV_PATH}"
        )
    return token


def _fetch_json(
    client: httpx.Client,
    dataset_id: str,
    params: dict[str, Any],
) -> Any:
    """Fetch JSON from the ODS exports endpoint.

    Tries the /exports/json endpoint first.  Falls back to /records if the
    exports endpoint returns a non-200 status.
    """
    token = _get_token()
    merged = {**params, "apikey": token}

    # Primary: /exports/json
    url_exports = f"{BASE_URL}/{dataset_id}/exports/json"
    resp = client.get(url_exports, params=merged, timeout=REQUEST_TIMEOUT)
    if resp.status_code == 200:
        return resp.json()

    # Fallback: /records
    url_records = f"{BASE_URL}/{dataset_id}/records"
    resp2 = client.get(url_records, params=merged, timeout=REQUEST_TIMEOUT)
    resp2.raise_for_status()
    body = resp2.json()
    # /records returns {"total_count": …, "results": [ { "record": { … } }, … ]}
    if isinstance(body, dict) and "records" in body:
        return [
            r.get("record", {}).get("fields", r) if isinstance(r, dict) else r
            for r in body["records"]
        ]
    if isinstance(body, dict) and "results" in body:
        return [
            r.get("record", {}).get("fields", r) if isinstance(r, dict) else r
            for r in body["results"]
        ]
    return body


# ---------------------------------------------------------------------------
# Schema discovery
# ---------------------------------------------------------------------------

def discover_schema(
    client: httpx.Client,
    dataset_id: str,
) -> list[str]:
    """Fetch 1 record to discover the field names for a dataset."""
    data = _fetch_json(client, dataset_id, {"limit": 1, "offset": 0})
    if not data:
        return []
    record = data[0] if isinstance(data, list) else data
    return sorted(record.keys())


# ---------------------------------------------------------------------------
# DDL generation
# ---------------------------------------------------------------------------

def _make_create_table_sql(
    table_name: str,
    fields: list[str],
) -> str:
    """Build a CREATE TABLE statement with all discovered columns as TEXT.

    Adds a primary key (first field or synthetic id), _raw JSON, and
    ingested_at timestamp.
    """
    col_defs = []
    for f in fields:
        safe = f'"{f}"'
        col_defs.append(f"    {safe} TEXT")
    col_defs.append('    "_raw" TEXT')
    col_defs.append('    "ingested_at" TEXT')

    # Use the first discovered field as the primary key if it looks like an id;
    # otherwise add a synthetic rowid.
    pk_field = None
    for candidate in ("id", "recordid", "record_id", fields[0] if fields else ""):
        if candidate in fields:
            pk_field = candidate
            break

    if pk_field:
        col_defs_str = ",\n".join(col_defs)
        ddl = f'CREATE TABLE IF NOT EXISTS "{table_name}" (\n{col_defs_str}\n);'
    else:
        col_defs_str = ",\n".join(col_defs)
        ddl = (
            f'CREATE TABLE IF NOT EXISTS "{table_name}" (\n'
            f'    "_synthetic_id" INTEGER PRIMARY KEY AUTOINCREMENT,\n'
            f'{col_defs_str}\n);'
        )
    return ddl


def ensure_table(
    conn: sqlite3.Connection,
    table_name: str,
    fields: list[str],
) -> None:
    """Create the table if it doesn't exist, using discovered field names."""
    ddl = _make_create_table_sql(table_name, fields)
    conn.executescript(ddl)


# ---------------------------------------------------------------------------
# Data fetch + store
# ---------------------------------------------------------------------------

def _normalise_competition(record: dict[str, Any]) -> dict[str, Any]:
    """Add normalised fields for flexibility_competitions records."""
    out = dict(record)
    for norm_name, src_name in COMPETITION_FIELD_MAP.items():
        out[f"_norm_{norm_name}"] = record.get(src_name)
    return out


def ingest_dataset(
    conn: sqlite3.Connection,
    client: httpx.Client,
    table_name: str,
    dataset_id: str,
) -> int:
    """Fetch all records for a dataset and store them in SQLite.

    Uses keyset pagination (WHERE sort_field > last_value) to work around
    the ODS offset + limit <= 10 000 ceiling.

    Returns the number of records inserted.
    """
    # 1. Discover schema from 1 record
    print(f"  Discovering schema for {dataset_id}...", flush=True)
    fields = discover_schema(client, dataset_id)
    if not fields:
        print(f"  WARNING: No records found for {dataset_id}", flush=True)
        return 0
    print(f"  Found {len(fields)} fields", flush=True)

    # Add normalised columns for competitions
    extra_fields: list[str] = []
    if table_name == "spen_competitions":
        extra_fields = [f"_norm_{k}" for k in COMPETITION_FIELD_MAP]

    all_fields = fields + extra_fields

    # 2. Create table
    ensure_table(conn, table_name, all_fields)
    conn.commit()
    print(f"  Table {table_name} ready", flush=True)

    # 3. Fetch and insert — strategy depends on sort_field
    sort_field = SORT_KEYS.get(table_name, fields[0])
    total_inserted = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    # Build the INSERT statement
    safe_cols = [f'"{f}"' for f in all_fields] + ['"_raw"', '"ingested_at"']
    placeholders = ", ".join(["?"] * len(safe_cols))
    col_list = ", ".join(safe_cols)
    insert_sql = f'INSERT OR REPLACE INTO "{table_name}" ({col_list}) VALUES ({placeholders})'

    if sort_field is None:
        # ---- Single-pass full export (limit=-1 returns ALL records) ----
        print("  Fetching full dataset (limit=-1)...", flush=True)
        data = _fetch_json(client, dataset_id, {"limit": -1})
        if data:
            rows: list[tuple] = []
            for record in data:
                if table_name == "spen_competitions":
                    record = _normalise_competition(record)
                raw_json = json.dumps(record, ensure_ascii=False, default=str)
                values = [record.get(f) for f in all_fields] + [raw_json, now_iso]
                values = [str(v) if v is not None else None for v in values]
                rows.append(tuple(values))
            conn.executemany(insert_sql, rows)
            conn.commit()
            total_inserted = len(rows)
        print(f"    Inserted {total_inserted} records", flush=True)
    else:
        # ---- Keyset pagination (WHERE sort_field >= last_value) ---------
        #   key_value  — current sort-field value being paginated
        #   key_offset — rows already returned with field >= key_value
        key_value: str | None = None
        key_offset: int = 0
        page = 0

        while True:
            page += 1
            qp: dict[str, Any] = {
                "limit": BATCH_SIZE,
                "sort": f"{sort_field} asc",
            }
            if key_value is not None:
                qp["where"] = f"{sort_field} >= '{key_value}'"
                qp["offset"] = key_offset
            else:
                qp["offset"] = 0

            where_desc = (
                f"{sort_field} >= {key_value!r} offset={key_offset}"
                if key_value
                else "(no filter)"
            )
            print(f"  Page {page}: {where_desc}, limit={BATCH_SIZE}...", flush=True)
            data = _fetch_json(client, dataset_id, qp)
            if not data:
                break

            rows = []
            for record in data:
                if table_name == "spen_competitions":
                    record = _normalise_competition(record)
                raw_json = json.dumps(record, ensure_ascii=False, default=str)
                values = [record.get(f) for f in all_fields] + [raw_json, now_iso]
                values = [str(v) if v is not None else None for v in values]
                rows.append(tuple(values))

            conn.executemany(insert_sql, rows)
            conn.commit()
            total_inserted += len(rows)

            new_key = str(data[-1].get(sort_field, ""))
            if new_key == key_value:
                key_offset += len(data)
            else:
                trailing = sum(
                    1 for r in reversed(data)
                    if str(r.get(sort_field, "")) == new_key
                )
                key_value = new_key
                key_offset = trailing

            print(
                f"    Inserted {total_inserted} records so far  "
                f"(key={key_value!r}, offset={key_offset})",
                flush=True,
            )

            if len(data) < BATCH_SIZE:
                break

    return total_inserted


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_spen_ingest() -> dict[str, int]:
    """Fetch all 3 SPEN datasets and store them in SQLite.

    Returns a dict mapping table name -> record count.
    """
    from .db import get_connection

    results: dict[str, int] = {}

    with httpx.Client() as client:
        with get_connection() as conn:
            for table_name, dataset_id in DATASETS.items():
                print(f"\n=== Ingesting {dataset_id} -> {table_name} ===", flush=True)
                count = ingest_dataset(conn, client, table_name, dataset_id)
                results[table_name] = count
                print(f"  Done: {count} records in {table_name}", flush=True)

    return results


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("SPEN Data Ingest Pipeline", flush=True)
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}", flush=True)
    print(f"Env file: {_ENV_PATH}", flush=True)
    print(f"Token present: {bool(os.getenv('SPEN_DATAPORTAL_TOKEN'))}", flush=True)
    counts = run_spen_ingest()
    print("\n=== Summary ===", flush=True)
    for tbl, cnt in counts.items():
        print(f"  {tbl}: {cnt} records", flush=True)
    print("Done.", flush=True)

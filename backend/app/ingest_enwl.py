"""ENWL data ingest pipeline for FlexCompass.

Fetches flexibility tender and postcode data from the Electricity North West
OpenDataSoft portal, normalises it, and stores in SQLite.

Datasets:
  - enwl-historical-flexibility-tender-site-requirements  (historical tenders)
  - enwl-flexibility-tender-site-requirements             (current tenders)
  - enwl-flexibility-tender-postcode-data                 (substation→postcode map)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

# Load .env before anything reads env vars
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)

from .db import get_connection  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://electricitynorthwest.opendatasoft.com/api/v2/catalog/datasets"

DATASETS: list[dict[str, Any]] = [
    {
        "id": "enwl-historical-flexibility-tender-site-requirements",
        "table": "enwl_tender_requirements_historical",
        "description": "Historical flexibility tender site requirements",
    },
    {
        "id": "enwl-flexibility-tender-site-requirements",
        "table": "enwl_tender_requirements",
        "description": "Current flexibility tender site requirements",
    },
    {
        "id": "enwl-flexibility-tender-postcode-data",
        "table": "enwl_postcode_data",
        "description": "Substation-to-postcode mapping",
    },
]

INGESTED_AT = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    """Return ENWL_DATAPORTAL_TOKEN from environment."""
    token = os.environ.get("ENWL_DATAPORTAL_TOKEN", "")
    if not token:
        raise RuntimeError(
            "ENWL_DATAPORTAL_TOKEN not set — check .env at project root"
        )
    return token


def fetch_dataset_records(
    dataset_id: str,
    limit: int | None = None,
    offset: int = 0,
    timeout: float = 120.0,
) -> list[dict[str, Any]]:
    """Fetch records from an ENWL OpenDataSoft dataset as a JSON list.

    Args:
        dataset_id: ODS dataset identifier.
        limit:      Max records (None = all available, omit param entirely).
        offset:     Starting offset.
        timeout:    HTTP timeout in seconds.

    Returns:
        List of record dicts (raw ODS fields).
    """
    api_key = _get_api_key()
    url = f"{BASE_URL}/{dataset_id}/exports/json"
    params: dict[str, Any] = {"apikey": api_key}
    if limit is not None:
        params["limit"] = limit
    if offset:
        params["offset"] = offset

    with httpx.Client(timeout=timeout) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Schema discovery & dynamic table creation
# ---------------------------------------------------------------------------

def _sqlite_type(value: Any) -> str:
    """Infer SQLite column type from a Python value."""
    if value is None:
        return "TEXT"
    if isinstance(value, bool):
        return "INTEGER"
    if isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "REAL"
    if isinstance(value, (dict, list)):
        return "TEXT"  # store as JSON text
    return "TEXT"


def _create_table_from_record(
    conn: Any,
    table_name: str,
    sample: dict[str, Any],
) -> None:
    """Dynamically create a SQLite table from a sample record's keys.

    Adds _raw (TEXT) and ingested_at (TEXT) columns automatically.
    Primary key is 'recordid' if present, otherwise a rowid.
    """
    cols = []
    for key, value in sample.items():
        col_type = _sqlite_type(value)
        if key == "recordid":
            cols.append(f'    "{key}" {col_type} PRIMARY KEY')
        else:
            cols.append(f'    "{key}" {col_type}')

    # Always add provenance columns
    cols.append("    _raw TEXT")
    cols.append("    ingested_at TEXT")

    col_defs = ",\n".join(cols)

    ddl = f'CREATE TABLE IF NOT EXISTS "{table_name}" (\n{col_defs}\n)'
    conn.execute(ddl)
    print(f"  [table] created/verified {table_name}")


# ---------------------------------------------------------------------------
# Record normalisation
# ---------------------------------------------------------------------------

def _normalise_record(record: dict[str, Any]) -> dict[str, Any]:
    """Normalise an ODS record for SQLite storage.

    - Serialize dict/list fields (geo_shape, geo_point_2d) as JSON text.
    - Store _raw as full JSON.
    - Add ingested_at timestamp.
    """
    out: dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, (dict, list)):
            out[key] = json.dumps(value, ensure_ascii=False)
        else:
            out[key] = value

    out["_raw"] = json.dumps(record, ensure_ascii=False)
    out["ingested_at"] = INGESTED_AT
    return out


def _clean_postcodes(raw: str | None) -> list[str]:
    """Clean ENWL postcodes: strip trailing spaces, split on comma.

    Example: "M1 2 ,M1 6 ,M1 7 " → ["M1 2", "M1 6", "M1 7"]
    """
    if not raw:
        return []
    parts = raw.split(",")
    cleaned = []
    for p in parts:
        p = p.strip()
        if p:
            # Collapse internal whitespace: "M1  2" → "M1 2"
            p = " ".join(p.split())
            cleaned.append(p)
    return cleaned


# ---------------------------------------------------------------------------
# Dataset ingest
# ---------------------------------------------------------------------------

def ingest_dataset(
    dataset_id: str,
    table_name: str,
    description: str,
) -> int:
    """Fetch and store all records from one ENWL dataset.

    Returns the number of records inserted.
    """
    print(f"\n{'='*60}")
    print(f"  Ingesting: {description}")
    print(f"  Dataset:   {dataset_id}")
    print(f"  Table:     {table_name}")
    print(f"{'='*60}")

    # Step 1: Fetch 1 record to discover schema
    print("  [fetch] discovering schema (1 record)...")
    sample_records = fetch_dataset_records(dataset_id, limit=1)
    if not sample_records:
        print("  [warn] no records returned — skipping")
        return 0

    sample = sample_records[0]
    field_names = list(sample.keys())
    print(f"  [schema] {len(field_names)} fields: {field_names[:8]}...")

    # Step 2: Create table dynamically
    with get_connection() as conn:
        _create_table_from_record(conn, table_name, sample)

    # Step 3: Fetch ALL records (limit=None → ODS returns everything)
    print("  [fetch] downloading all records...")
    records = fetch_dataset_records(dataset_id)
    total = len(records)
    print(f"  [fetch] received {total} records")

    if total == 0:
        return 0

    # Step 4: Normalise and insert
    print("  [store] inserting records...")
    sample_normalised = _normalise_record(records[0])
    col_names = list(sample_normalised.keys())
    placeholders = ", ".join(["?"] * len(col_names))
    col_list = ", ".join([f'"{c}"' for c in col_names])
    sql = f'INSERT OR REPLACE INTO "{table_name}" ({col_list}) VALUES ({placeholders})'

    with get_connection() as conn:
        batch: list[tuple] = []
        for i, rec in enumerate(records):
            norm = _normalise_record(rec)
            row = tuple(norm.get(c) for c in col_names)
            batch.append(row)

            if len(batch) >= 500:
                conn.executemany(sql, batch)
                batch = []
                print(f"    ... {i+1}/{total} inserted")

        if batch:
            conn.executemany(sql, batch)

        print(f"  [done] {total} records in {table_name}")

    return total


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_enwl_ingest() -> dict[str, int]:
    """Run the full ENWL ingest pipeline.

    Returns:
        Dict mapping dataset_id → record count for each dataset.
    """
    print("\n" + "=" * 60)
    print("  ENWL Data Ingest Pipeline")
    print(f"  Started: {INGESTED_AT}")
    print("=" * 60)

    results: dict[str, int] = {}

    for ds in DATASETS:
        try:
            count = ingest_dataset(ds["id"], ds["table"], ds["description"])
            results[ds["id"]] = count
        except Exception as exc:
            print(f"\n  [ERROR] Failed to ingest {ds['id']}: {exc}")
            results[ds["id"]] = -1

    # Summary
    print("\n" + "=" * 60)
    print("  ENWL Ingest Summary")
    print("=" * 60)
    for ds in DATASETS:
        count = results.get(ds["id"], -1)
        status = "✓" if count >= 0 else "✗"
        print(f"  {status} {ds['table']:45s} → {count:>6} records")
    print("=" * 60 + "\n")

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    counts = run_enwl_ingest()
    total = sum(c for c in counts.values() if c > 0)
    print(f"Total records ingested: {total}")
    sys.exit(0 if all(c >= 0 for c in counts.values()) else 1)

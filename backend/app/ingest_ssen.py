"""SSEN data ingest — fetch from CKAN portal and store in SQLite.

Key datasets:
  1. Contract Register (Call Off Contracts): 1,381 records
  2. Long-term Bidding Postcode Lists: 15,741 postcodes (SEPD + SHEPD)
  3. Dispatch Reports: weekly dispatch data (21 resources)
"""

from __future__ import annotations

import json
import time

import httpx

from .db import get_connection

CKAN_BASE = "https://ckan-prod.sse.datopian.com/api/3/action"


def _fetch_datastore(resource_id: str, limit: int = 10000, offset: int = 0) -> list[dict]:
    """Fetch records from CKAN datastore with retry."""
    for attempt in range(3):
        try:
            r = httpx.get(f"{CKAN_BASE}/datastore_search",
                          params={"resource_id": resource_id, "limit": limit, "offset": offset},
                          timeout=30)
            if r.status_code == 403:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json().get("result", {}).get("records", [])
        except httpx.RequestError:
            if attempt < 2:
                time.sleep(2)
                continue
            raise
    return []


def _get_package_resources(package_id: str) -> list[dict]:
    """Get all datastore-active resources for a package."""
    r = httpx.get(f"{CKAN_BASE}/package_show", params={"id": package_id}, timeout=20)
    r.raise_for_status()
    pkg = r.json().get("result", {})
    return [r for r in pkg.get("resources", []) if r.get("datastore_active")]


def _ensure_ssen_tables():
    """Create SSEN ingest tables."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ssen_contracts (
                _id INTEGER PRIMARY KEY,
                cmz_name TEXT,
                licence_area TEXT,
                date_of_release TEXT,
                asset_name TEXT,
                technology_type TEXT,
                flexibility_service_provider TEXT,
                contracted_capacity_mw REAL,
                _raw TEXT,
                ingested_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS ssen_postcodes (
                _id INTEGER PRIMARY KEY,
                area TEXT,
                primary_substation TEXT,
                cmz TEXT,
                postcode TEXT,
                licence_area TEXT,
                _raw TEXT,
                ingested_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS ssen_dispatch (
                _id INTEGER PRIMARY KEY,
                offer_number TEXT,
                asset TEXT,
                incident_reference TEXT,
                provider TEXT,
                service_type TEXT,
                instructed_capacity_mw REAL,
                instructed_volume_mwh REAL,
                week TEXT,
                _raw TEXT,
                ingested_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS ssen_bidding_requirements (
                _id INTEGER PRIMARY KEY,
                cmz_name TEXT,
                licence_area TEXT,
                date_of_release TEXT,
                service_type_required TEXT,
                peak_capacity_required REAL,
                service_year TEXT,
                delivery_period TEXT,
                _raw TEXT,
                ingested_at TEXT DEFAULT (datetime('now'))
            );
        """)


def ingest_ssen_contracts() -> int:
    """Ingest SSEN Call Off Contracts (1,381 records)."""
    _ensure_ssen_tables()
    print("[SSEN] Fetching contract register...")
    resources = _get_package_resources("flexibility-services-contract-register")

    total = 0
    for res in resources:
        name = res.get("name", "")
        if "call off contracts" not in name.lower():
            continue
        rid = res["id"]
        records = _fetch_datastore(rid)
        if not records:
            continue
        print(f"  {name}: {len(records)} records")
        with get_connection() as conn:
            for r in records:
                rid_val = r.get("_id")
                if rid_val is None:
                    continue
                conn.execute("""
                    INSERT OR REPLACE INTO ssen_contracts
                    (_id, cmz_name, licence_area, date_of_release, asset_name,
                     technology_type, flexibility_service_provider, contracted_capacity_mw, _raw)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    rid_val,
                    r.get("CMZ Name"), r.get("Licence Area"),
                    r.get("Date of Release"), r.get("Asset Name"),
                    r.get("Technology Type"), r.get("Flexibility Service Provider"),
                    r.get("contracted_capacity__mw_"),
                    json.dumps(r, default=str),
                ))
        total += len(records)
    print(f"[SSEN] Stored {total:,} contracts")
    return total


def ingest_ssen_postcodes() -> int:
    """Ingest SSEN postcode lists from long-term bidding (15k+ postcodes)."""
    _ensure_ssen_tables()
    print("[SSEN] Fetching postcode lists...")
    resources = _get_package_resources("long-term-bidding")

    total = 0
    for res in resources:
        name = res.get("name", "")
        if "postcode" not in name.lower():
            continue
        rid = res["id"]
        records = _fetch_datastore(rid)
        if not records:
            continue

        # Determine licence area from name
        licence = "SEPD" if "sepd" in name.lower() else "SHEPD" if "shepd" in name.lower() else "SSEN"
        print(f"  {name}: {len(records)} records ({licence})")

        with get_connection() as conn:
            for r in records:
                pc = (r.get("Postcode") or "").strip()
                if not pc:
                    continue
                conn.execute("""
                    INSERT OR REPLACE INTO ssen_postcodes
                    (_id, area, primary_substation, cmz, postcode, licence_area, _raw)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    r.get("_id"),
                    r.get("Area"), r.get("Primary"),
                    r.get("CMZ"), pc, licence,
                    json.dumps(r, default=str),
                ))
                total += 1
    print(f"[SSEN] Stored {total:,} postcodes")
    return total


def ingest_ssen_dispatch() -> int:
    """Ingest SSEN dispatch reports (weekly, across 21 resources)."""
    _ensure_ssen_tables()
    print("[SSEN] Fetching dispatch reports...")
    resources = _get_package_resources("flexibility-dispatch-report")

    total = 0
    for res in resources:
        name = res.get("name", "")
        rid = res["id"]
        records = _fetch_datastore(rid)
        if not records:
            continue

        # Extract week from name
        week = name.replace("Dispatch Report", "").replace("Dispatch report", "").strip()

        with get_connection() as conn:
            for r in records:
                rid_val = r.get("_id")
                if rid_val is None:
                    continue
                conn.execute("""
                    INSERT OR REPLACE INTO ssen_dispatch
                    (_id, offer_number, asset, incident_reference, provider,
                     service_type, instructed_capacity_mw, instructed_volume_mwh,
                     week, _raw)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    rid_val,
                    r.get("Offer Number"), r.get("Asset"),
                    r.get("Incident Reference"), r.get("Provider"),
                    r.get("Service Type"),
                    r.get("instructed_flex_capacity__mw_"),
                    r.get("instructed_flex_volume__mwh_"),
                    week,
                    json.dumps(r, default=str),
                ))
        total += len(records)
        if total % 500 == 0:
            print(f"  ... {total:,} dispatch records")

    print(f"[SSEN] Stored {total:,} dispatch records")
    return total


def ingest_ssen_bidding_requirements() -> int:
    """Ingest SSEN Call Off Bidding Requirements (619 records)."""
    _ensure_ssen_tables()
    print("[SSEN] Fetching bidding requirements...")
    resources = _get_package_resources("flexibility-services-contract-register")

    total = 0
    for res in resources:
        name = res.get("name", "")
        if "bidding requirements" not in name.lower():
            continue
        rid = res["id"]
        records = _fetch_datastore(rid)
        if not records:
            continue
        print(f"  {name}: {len(records)} records")
        with get_connection() as conn:
            for r in records:
                rid_val = r.get("_id")
                if rid_val is None:
                    continue
                conn.execute("""
                    INSERT OR REPLACE INTO ssen_bidding_requirements
                    (_id, cmz_name, licence_area, date_of_release,
                     service_type_required, peak_capacity_required,
                     service_year, delivery_period, _raw)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    rid_val,
                    r.get("CMZ Name"), r.get("Licence Area"),
                    r.get("Date of Release"),
                    r.get("Flexibility Service Type Required"),
                    r.get("across_all_delivery_years_per_cmz__sum_of_peak_capacity_requ"),
                    r.get("service_year_s_"), r.get("delivery_period_s_"),
                    json.dumps(r, default=str),
                ))
        total += len(records)
    print(f"[SSEN] Stored {total:,} bidding requirements")
    return total


def run_ssen_ingest() -> dict[str, int]:
    """Run full SSEN ingest pipeline."""
    counts = {}
    counts["contracts"] = ingest_ssen_contracts()
    counts["postcodes"] = ingest_ssen_postcodes()
    counts["dispatch"] = ingest_ssen_dispatch()
    counts["bidding_requirements"] = ingest_ssen_bidding_requirements()
    return counts

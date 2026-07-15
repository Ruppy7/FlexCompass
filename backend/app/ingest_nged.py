"""NGED data ingest — fetch from CKAN portal and store in SQLite.

Datasets:
  1. WHERE All Postcodes (75k) — postcode→CMZ crosswalk
  2. Procurement Report (capped at 50k) — procurement outcomes
  3. Dispatch Report (38k) — dispatch events
  4. Trade Results Summary (3.4k) — trade outcomes
"""

from __future__ import annotations

import json
import os
import time

import httpx

from .db import get_connection

CKAN_BASE = "https://connecteddata.nationalgrid.co.uk/api/3/action"


def _get_headers() -> dict[str, str]:
    token = os.getenv("NGED_DATAPORTAL_TOKEN", "")
    return {"Authorization": token, "Accept": "application/json"}


def _get_resource_id(package: str, name_contains: str) -> str | None:
    """Find a resource ID by package name and resource name substring."""
    r = httpx.get(f"{CKAN_BASE}/package_show", params={"id": package},
                  headers=_get_headers(), timeout=30)
    r.raise_for_status()
    pkg = r.json().get("result", {})
    for res in pkg.get("resources", []):
        if name_contains.lower() in res.get("name", "").lower():
            return res["id"]
    return None


def _fetch_datastore(resource_id: str, limit: int = 10000, offset: int = 0) -> list[dict]:
    """Fetch records from CKAN datastore with retry for Cloudflare."""
    for attempt in range(4):
        try:
            r = httpx.get(f"{CKAN_BASE}/datastore_search",
                          params={"resource_id": resource_id, "limit": limit, "offset": offset},
                          headers=_get_headers(), timeout=60)
            if r.status_code == 403:
                wait = 2 ** (attempt + 1)
                print(f"  ... 403 received, retrying in {wait}s (attempt {attempt+1}/4)")
                time.sleep(wait)
                continue
            r.raise_for_status()
            result = r.json().get("result", {})
            return result.get("records", [])
        except httpx.RequestError:
            if attempt < 3:
                time.sleep(2 ** (attempt + 1))
                continue
            raise
    return []


def _fetch_all_datastore(resource_id: str, max_records: int = 0, batch: int = 10000) -> list[dict]:
    """Fetch all records from a datastore with pagination."""
    all_records = []
    offset = 0
    while True:
        records = _fetch_datastore(resource_id, limit=batch, offset=offset)
        if not records:
            break
        all_records.extend(records)
        offset += len(records)
        if max_records and len(all_records) >= max_records:
            all_records = all_records[:max_records]
            break
        if len(records) < batch:
            break
        print(f"  ... {len(all_records):,} records fetched")
    return all_records


def _ensure_nged_tables():
    """Create NGED ingest tables if they don't exist."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS postcode_zone_map (
                postcode TEXT NOT NULL,
                hv_cmz_code TEXT,
                hv_zone_name TEXT,
                lv_cmz_code TEXT,
                lv_zone_name TEXT,
                primary_substation TEXT,
                primary_substation_number TEXT,
                gsp_name TEXT,
                dso TEXT NOT NULL DEFAULT 'NGED',
                ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (postcode, dso)
            );

            CREATE TABLE IF NOT EXISTS nged_procurement (
                _id INTEGER PRIMARY KEY,
                tender_reference TEXT,
                product TEXT,
                constraint_licence_area TEXT,
                provider_licence_area TEXT,
                service_location_gsp TEXT,
                service_provider TEXT,
                constraint_trigger TEXT,
                cmz_name TEXT,
                max_connection_voltage TEXT,
                main_technology TEXT,
                peak_flexible_capacity_mw REAL,
                _raw TEXT,
                ingested_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS nged_dispatch (
                _id INTEGER PRIMARY KEY,
                tender_reference TEXT,
                incident_reference TEXT,
                product TEXT,
                constraint_licence_area TEXT,
                provider_licence_area TEXT,
                incident_location_gsp TEXT,
                accepting_party TEXT,
                flexible_unit_reference TEXT,
                main_technology TEXT,
                dispatch_capacity_mw REAL,
                dispatch_volume_mwh REAL,
                _raw TEXT,
                ingested_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS nged_trade_results (
                _id INTEGER PRIMARY KEY,
                cmz_code TEXT,
                flexibility_product TEXT,
                trade_opportunity_name TEXT,
                trade_window TEXT,
                company_name TEXT,
                offered_capacity_kw REAL,
                offered_availability_price REAL,
                offered_utilisation_price REAL,
                trade_outcome TEXT,
                accepted_capacity_kw REAL,
                awarded_availability_price REAL,
                technology_type TEXT,
                number_of_assets INTEGER,
                total_asset_installed_capacity REAL,
                _raw TEXT,
                ingested_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)


def ingest_nged_postcodes() -> int:
    """Ingest WHERE All Postcodes (75k records) — the primary join table."""
    _ensure_nged_tables()
    print("[NGED] Fetching WHERE All Postcodes...")
    rid = _get_resource_id("flexibility-forecasts", "postcodes")
    if not rid:
        print("[NGED] Could not find postcode resource")
        return 0

    records = _fetch_all_datastore(rid)
    print(f"[NGED] Storing {len(records):,} postcodes...")
    with get_connection() as conn:
        for r in records:
            pc = r.get("Postcode", "").strip()
            if not pc:
                continue
            conn.execute("""
                INSERT OR REPLACE INTO postcode_zone_map
                (postcode, hv_cmz_code, hv_zone_name, lv_cmz_code, lv_zone_name,
                 primary_substation, primary_substation_number, gsp_name, dso)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'NGED')
            """, (
                pc,
                r.get("HV CMZ Code"), r.get("HV Zone Name"),
                r.get("LV CMZ Code"), r.get("LV Zone Name"),
                r.get("Primary Substation Name"), r.get("Primary Substation Number"),
                r.get("GSP Name"),
            ))
    print(f"[NGED] Stored {len(records):,} postcodes")
    return len(records)


def ingest_nged_procurement(max_records: int = 50000) -> int:
    """Ingest Procurement Report (capped at max_records)."""
    _ensure_nged_tables()
    print(f"[NGED] Fetching Procurement Report (max {max_records:,})...")
    rid = _get_resource_id("flexibility-reports", "procurement report")
    if not rid:
        print("[NGED] Could not find procurement resource")
        return 0

    records = _fetch_all_datastore(rid, max_records=max_records)
    print(f"[NGED] Storing {len(records):,} procurement records...")
    with get_connection() as conn:
        for r in records:
            rid_val = r.get("_id")
            if rid_val is None:
                continue
            conn.execute("""
                INSERT OR REPLACE INTO nged_procurement
                (_id, tender_reference, product, constraint_licence_area,
                 provider_licence_area, service_location_gsp, service_provider,
                 constraint_trigger, cmz_name, max_connection_voltage,
                 main_technology, peak_flexible_capacity_mw, _raw)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rid_val,
                r.get("Tender Reference"), r.get("Product"),
                r.get("Constraint Licence Area"), r.get("Provider Licence Area"),
                r.get("Service Location (GSP)"), r.get("Service Provider"),
                r.get("Constraint Trigger"), r.get("CMZ Name"),
                r.get("Maximum Connection Voltage"), r.get("Main Technology"),
                r.get("Peak Flexible Capacity MW"),
                json.dumps(r, default=str),
            ))
    print(f"[NGED] Stored {len(records):,} procurement records")
    return len(records)


def ingest_nged_dispatch() -> int:
    """Ingest Dispatch Report (38k records)."""
    _ensure_nged_tables()
    print("[NGED] Fetching Dispatch Report...")
    rid = _get_resource_id("flexibility-reports", "dispatch report")
    if not rid:
        print("[NGED] Could not find dispatch resource")
        return 0

    records = _fetch_all_datastore(rid)
    print(f"[NGED] Storing {len(records):,} dispatch records...")
    with get_connection() as conn:
        for r in records:
            rid_val = r.get("_id")
            if rid_val is None:
                continue
            conn.execute("""
                INSERT OR REPLACE INTO nged_dispatch
                (_id, tender_reference, incident_reference, product,
                 constraint_licence_area, provider_licence_area,
                 incident_location_gsp, accepting_party,
                 flexible_unit_reference, main_technology,
                 dispatch_capacity_mw, dispatch_volume_mwh, _raw)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rid_val,
                r.get("Tender Reference"), r.get("Incident Reference"),
                r.get("Product"), r.get("Constraint Licence Area"),
                r.get("Provider Licence Area"), r.get("Incident location (GSP)"),
                r.get("Accepting Party"), r.get("Flexible Unit Reference"),
                r.get("Main Technology"), r.get("Dispatch Capacity MW"),
                r.get("Dispatch Volume MWh"),
                json.dumps(r, default=str),
            ))
    print(f"[NGED] Stored {len(records):,} dispatch records")
    return len(records)


def ingest_nged_trade_results() -> int:
    """Ingest Trade Results Summary (3.4k records)."""
    _ensure_nged_tables()
    print("[NGED] Fetching Trade Results Summary...")
    rid = _get_resource_id("flexibility-trades-data-and-results", "trade results summary")
    if not rid:
        print("[NGED] Could not find trade results resource")
        return 0

    records = _fetch_all_datastore(rid)
    print(f"[NGED] Storing {len(records):,} trade results...")
    with get_connection() as conn:
        for r in records:
            rid_val = r.get("_id")
            if rid_val is None:
                continue
            conn.execute("""
                INSERT OR REPLACE INTO nged_trade_results
                (_id, cmz_code, flexibility_product, trade_opportunity_name,
                 trade_window, company_name, offered_capacity_kw,
                 offered_availability_price, offered_utilisation_price,
                 trade_outcome, accepted_capacity_kw, awarded_availability_price,
                 technology_type, number_of_assets, total_asset_installed_capacity, _raw)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rid_val,
                r.get("CMZ Code"), r.get("Flexibility Product"),
                r.get("Trade Opportunity Name"), r.get("Trade Windows"),
                r.get("Company Name"), r.get("Offered Capacity [kW]"),
                r.get("Offered Availability Price"),
                r.get("Offered Utilisation Price"),
                r.get("Trade Outcome"), r.get("Accepted Capacity [kW]"),
                r.get("Awarded Availability Price"),
                r.get("Technology Type"), r.get("Number of Assets"),
                r.get("Total Asset Installed Capacity"),
                json.dumps(r, default=str),
            ))
    print(f"[NGED] Stored {len(records):,} trade results")
    return len(records)

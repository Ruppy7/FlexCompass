"""Populate the SQLite database from JSON seed files.

Run once (idempotent — uses INSERT OR REPLACE). After seeding, the DB
is the source of truth and the API can switch to reading from it.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .config import config
from .db import get_connection, run_migrations
from .seed_loader import SEED_DIR


def _load_json(filename: str) -> list[dict]:
    path = SEED_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def seed_portal_datasets(conn: sqlite3.Connection) -> int:
    rows = _load_json("portal_datasets.json")
    for r in rows:
        conn.execute(
            """INSERT OR REPLACE INTO portal_datasets
               (id, name, portal_url, api_url, record_count, last_modified,
                licence, fields_json, useful_for_json, limitations_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r["id"], r["name"], r["portal_url"],
                r.get("api_url"), r.get("record_count"), r.get("last_modified"),
                r.get("licence"),
                json.dumps(r.get("fields", [])),
                json.dumps(r.get("useful_for", [])),
                json.dumps(r.get("limitations", [])),
            ),
        )
    return len(rows)


def seed_flex_zones(conn: sqlite3.Connection) -> int:
    rows = _load_json("flex_zones.json")
    for r in rows:
        conn.execute(
            """INSERT OR REPLACE INTO flex_zones
               (zone_id, dso, platform, area_name, zone_type,
                postcode_prefixes_json, postcodes_json, geometry_json,
                source_dataset_id, raw_record_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r["zone_id"], r["dso"], r.get("platform"),
                r["area_name"], r.get("zone_type", "unknown"),
                json.dumps(r.get("postcode_prefixes", [])),
                json.dumps(r.get("postcodes", [])),
                json.dumps(r["geometry"]) if r.get("geometry") else None,
                r.get("source_dataset_id"),
                json.dumps(r["raw_record"]) if r.get("raw_record") else None,
            ),
        )
    return len(rows)


def seed_flex_signals(conn: sqlite3.Connection) -> int:
    rows = _load_json("flex_signals.json")
    for r in rows:
        conn.execute(
            """INSERT OR REPLACE INTO flex_signals
               (signal_id, zone_id, dso, platform, market_name, area_name,
                location_type, location_reference, service_type, direction,
                requirement_type, tender_round, historic_current_future_status,
                procurement_type, window_start, window_end, duration_minutes,
                lead_time, capacity_kw, guide_price, price_unit,
                utilisation_estimate, payment_type, eligible_asset_types_json,
                source_id, source_updated_at, source_dataset_id,
                raw_record_json, confidence_level, missing_fields_json,
                data_quality_notes_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r["signal_id"], r.get("zone_id"), r["dso"], r.get("platform"),
                r["market_name"], r["area_name"],
                r.get("location_type", "unknown"), r.get("location_reference", ""),
                r["service_type"], r.get("direction"),
                r.get("requirement_type"), r.get("tender_round"),
                r.get("historic_current_future_status", "unknown"),
                r["procurement_type"],
                r.get("window_start"), r.get("window_end"),
                r.get("duration_minutes"), r.get("lead_time"),
                r.get("capacity_kw"), r.get("guide_price"), r.get("price_unit"),
                r.get("utilisation_estimate"), r.get("payment_type"),
                json.dumps(r.get("eligible_asset_types", [])),
                r.get("source_id"), r.get("source_updated_at"),
                r.get("source_dataset_id"),
                json.dumps(r["raw_record"]) if r.get("raw_record") else None,
                r.get("confidence_level", "unknown"),
                json.dumps(r.get("missing_fields", [])),
                json.dumps(r.get("data_quality_notes", [])),
            ),
        )
    return len(rows)


def seed_data_sources(conn: sqlite3.Connection) -> int:
    rows = _load_json("data_sources.json")
    for r in rows:
        conn.execute(
            """INSERT OR REPLACE INTO data_sources
               (source_id, owner, source_name, source_type, access_method,
                original_reference, live_or_curated, date_accessed,
                represented_period, licence_notes, update_frequency,
                data_quality_notes_json, limitations_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r["source_id"], r["owner"], r["source_name"],
                r["source_type"], r["access_method"], r["original_reference"],
                r["live_or_curated"], r["date_accessed"],
                r["represented_period"], r["licence_notes"],
                r["update_frequency"],
                json.dumps(r.get("data_quality_notes", [])),
                json.dumps(r.get("limitations", [])),
            ),
        )
    return len(rows)


def seed_market_rules(conn: sqlite3.Connection) -> int:
    rows = _load_json("market_rules.json")
    for r in rows:
        conn.execute(
            """INSERT OR REPLACE INTO market_rules
               (rule_id, market_name, buyer, procurement_method, payment_type,
                eligible_provider_types_json, eligible_asset_types_json,
                minimum_capacity_kw, metering_requirements, baseline_requirements,
                stacking_notes, participation_notes, source_id, confidence_level)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r["rule_id"], r["market_name"], r["buyer"],
                r["procurement_method"], r["payment_type"],
                json.dumps(r.get("eligible_provider_types", [])),
                json.dumps(r.get("eligible_asset_types", [])),
                r.get("minimum_capacity_kw", 0),
                r["metering_requirements"], r["baseline_requirements"],
                r["stacking_notes"], r["participation_notes"],
                r["source_id"], r.get("confidence_level", "unknown"),
            ),
        )
    return len(rows)


def seed_all(db_path: Path | None = None) -> dict[str, int]:
    """Run migrations then seed all tables from JSON. Returns counts."""
    run_migrations(db_path)
    counts = {}
    with get_connection(db_path) as conn:
        counts["portal_datasets"] = seed_portal_datasets(conn)
        counts["flex_zones"] = seed_flex_zones(conn)
        counts["flex_signals"] = seed_flex_signals(conn)
        counts["data_sources"] = seed_data_sources(conn)
        counts["market_rules"] = seed_market_rules(conn)
    return counts


if __name__ == "__main__":
    counts = seed_all()
    print("Seeded:")
    for table, count in counts.items():
        print(f"  {table}: {count} rows")
    print(f"DB: {config.db_path}")

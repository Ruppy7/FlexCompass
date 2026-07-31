"""SQLite persistence layer for FlexCompass — no ORM.

Tables mirror the Pydantic models. All writes go through explicit SQL.
A `portal_cache` table stores raw portal API responses for local caching.
A `schema_version` table tracks applied migrations.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generator

from .config import config

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
-- Schema version tracker
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Portal dataset metadata
CREATE TABLE IF NOT EXISTS portal_datasets (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    portal_url      TEXT NOT NULL,
    api_url         TEXT,
    record_count    INTEGER,
    last_modified   TEXT,
    licence         TEXT,
    fields_json     TEXT NOT NULL DEFAULT '[]',
    useful_for_json TEXT NOT NULL DEFAULT '[]',
    limitations_json TEXT NOT NULL DEFAULT '[]'
);

-- Flex zones — the authoritative geographic unit
CREATE TABLE IF NOT EXISTS flex_zones (
    zone_id             TEXT PRIMARY KEY,
    dso                 TEXT NOT NULL,
    platform            TEXT,
    area_name           TEXT NOT NULL,
    zone_type           TEXT NOT NULL DEFAULT 'unknown',
    postcode_prefixes_json TEXT NOT NULL DEFAULT '[]',
    postcodes_json      TEXT NOT NULL DEFAULT '[]',
    geometry_json       TEXT,
    source_dataset_id   TEXT,
    raw_record_json     TEXT
);

-- Flex signals — per-zone flexibility signal
CREATE TABLE IF NOT EXISTS flex_signals (
    signal_id               TEXT PRIMARY KEY,
    zone_id                 TEXT,
    dso                     TEXT NOT NULL,
    platform                TEXT,
    market_name             TEXT NOT NULL,
    area_name               TEXT NOT NULL,
    location_type           TEXT NOT NULL DEFAULT 'unknown',
    location_reference      TEXT NOT NULL DEFAULT '',
    service_type            TEXT NOT NULL,
    direction               TEXT,
    requirement_type        TEXT,
    tender_round            TEXT,
    historic_current_future_status TEXT NOT NULL DEFAULT 'unknown',
    procurement_type        TEXT NOT NULL,
    window_start            TEXT,
    window_end              TEXT,
    duration_minutes        REAL,
    lead_time               TEXT,
    capacity_kw             REAL,
    guide_price             REAL,
    price_unit              TEXT,
    utilisation_estimate    TEXT,
    payment_type            TEXT,
    eligible_asset_types_json TEXT NOT NULL DEFAULT '[]',
    source_id               TEXT,
    source_updated_at       TEXT,
    source_dataset_id       TEXT,
    raw_record_json         TEXT,
    confidence_level        TEXT NOT NULL DEFAULT 'unknown',
    missing_fields_json     TEXT NOT NULL DEFAULT '[]',
    data_quality_notes_json TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY (zone_id) REFERENCES flex_zones(zone_id)
);

-- Data sources (v0 backward compat)
CREATE TABLE IF NOT EXISTS data_sources (
    source_id           TEXT PRIMARY KEY,
    owner               TEXT NOT NULL,
    source_name         TEXT NOT NULL,
    source_type         TEXT NOT NULL,
    access_method       TEXT NOT NULL,
    original_reference  TEXT NOT NULL,
    live_or_curated     TEXT NOT NULL,
    date_accessed       TEXT NOT NULL,
    represented_period  TEXT NOT NULL,
    licence_notes       TEXT NOT NULL,
    update_frequency    TEXT NOT NULL,
    data_quality_notes_json TEXT NOT NULL DEFAULT '[]',
    limitations_json    TEXT NOT NULL DEFAULT '[]'
);

-- Market rules (v0 backward compat)
CREATE TABLE IF NOT EXISTS market_rules (
    rule_id                 TEXT PRIMARY KEY,
    market_name             TEXT NOT NULL,
    buyer                   TEXT NOT NULL,
    procurement_method      TEXT NOT NULL,
    payment_type            TEXT NOT NULL,
    eligible_provider_types_json TEXT NOT NULL DEFAULT '[]',
    eligible_asset_types_json    TEXT NOT NULL DEFAULT '[]',
    minimum_capacity_kw     REAL NOT NULL DEFAULT 0,
    metering_requirements   TEXT NOT NULL,
    baseline_requirements   TEXT NOT NULL,
    stacking_notes          TEXT NOT NULL,
    participation_notes     TEXT NOT NULL,
    source_id               TEXT NOT NULL,
    confidence_level        TEXT NOT NULL DEFAULT 'unknown'
);

-- Asset groups (real or synthetic)
CREATE TABLE IF NOT EXISTS asset_groups (
    asset_group_id              TEXT PRIMARY KEY,
    source                      TEXT NOT NULL DEFAULT 'synthetic',
    asset_type                  TEXT NOT NULL,
    asset_count                 INTEGER NOT NULL,
    postcode                    TEXT,
    postcode_prefix             TEXT,
    rated_power_kw              REAL NOT NULL,
    controllable_power_kw       REAL NOT NULL,
    availability_percent        REAL NOT NULL,
    response_reliability_percent REAL NOT NULL,
    supported_service_types_json TEXT NOT NULL DEFAULT '[]',
    regional_distribution_json  TEXT NOT NULL DEFAULT '{}',
    postcode_distribution_json  TEXT NOT NULL DEFAULT '{}',
    baseline_assumption         TEXT NOT NULL DEFAULT '',
    metering_assumption         TEXT NOT NULL DEFAULT '',
    operational_notes_json      TEXT NOT NULL DEFAULT '[]'
);

-- Asset-signal matches
CREATE TABLE IF NOT EXISTS asset_signal_matches (
    match_id                TEXT PRIMARY KEY,
    asset_group_id          TEXT NOT NULL,
    signal_id               TEXT NOT NULL,
    mapped_zone_id          TEXT,
    estimated_available_kw  REAL NOT NULL,
    capacity_method         TEXT NOT NULL DEFAULT 'v0.1_heuristic',
    geography_match         TEXT,
    service_match           TEXT,
    capacity_plausibility   TEXT,
    data_completeness       TEXT,
    investigation_priority  TEXT,
    evidence_json           TEXT NOT NULL DEFAULT '[]',
    missing_information_json TEXT NOT NULL DEFAULT '[]',
    risks_json              TEXT NOT NULL DEFAULT '[]',
    next_steps_json         TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY (asset_group_id) REFERENCES asset_groups(asset_group_id),
    FOREIGN KEY (signal_id) REFERENCES flex_signals(signal_id)
);

-- Raw portal response cache
CREATE TABLE IF NOT EXISTS portal_cache (
    cache_key       TEXT PRIMARY KEY,
    portal_id       TEXT NOT NULL,
    url             TEXT NOT NULL,
    response_json   TEXT NOT NULL,
    fetched_at      TEXT NOT NULL DEFAULT (datetime('now')),
    record_count    INTEGER,
    etag            TEXT,
    content_hash    TEXT
);

-- Indices for common lookups
CREATE INDEX IF NOT EXISTS idx_flex_signals_zone ON flex_signals(zone_id);
CREATE INDEX IF NOT EXISTS idx_flex_signals_dso ON flex_signals(dso);
CREATE INDEX IF NOT EXISTS idx_flex_zones_dso ON flex_zones(dso);
CREATE INDEX IF NOT EXISTS idx_portal_cache_portal ON portal_cache(portal_id);
CREATE INDEX IF NOT EXISTS idx_asset_signal_matches_signal ON asset_signal_matches(signal_id);
"""),
    # -- Migration 2: NGED data ingest tables --
    (2, """
-- NGED WHERE All Postcodes → zone mapping
CREATE TABLE IF NOT EXISTS postcode_zone_map (
    postcode            TEXT PRIMARY KEY,
    hv_cmz_code         TEXT,
    hv_zone_name        TEXT,
    lv_cmz_code         TEXT,
    lv_zone_name        TEXT,
    primary_substation  TEXT,
    primary_substation_number TEXT,
    gsp_name            TEXT,
    dso                 TEXT NOT NULL DEFAULT 'NGED',
    ingested_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pzm_gsp ON postcode_zone_map(gsp_name);
CREATE INDEX IF NOT EXISTS idx_pzm_hv_cmz ON postcode_zone_map(hv_cmz_code);

-- NGED Procurement Report
CREATE TABLE IF NOT EXISTS nged_procurement (
    _id                         INTEGER PRIMARY KEY,
    tender_reference            TEXT,
    product                     TEXT,
    constraint_licence_area     TEXT,
    provider_licence_area       TEXT,
    service_location_gsp        TEXT,
    service_provider            TEXT,
    constraint_trigger          TEXT,
    cmz_name                    TEXT,
    maximum_connection_voltage  TEXT,
    main_technology             TEXT,
    peak_flexible_capacity_mw   REAL,
    _raw                        TEXT,
    ingested_at                 TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_nged_proc_tender ON nged_procurement(tender_reference);
CREATE INDEX IF NOT EXISTS idx_nged_proc_cmz ON nged_procurement(cmz_name);

-- NGED Dispatch Report
CREATE TABLE IF NOT EXISTS nged_dispatch (
    _id                         INTEGER PRIMARY KEY,
    tender_reference            TEXT,
    incident_reference          TEXT,
    product                     TEXT,
    constraint_licence_area     TEXT,
    provider_licence_area       TEXT,
    incident_location_gsp       TEXT,
    accepting_party             TEXT,
    flexible_unit_reference     TEXT,
    main_technology             TEXT,
    dispatch_capacity_mw        REAL,
    dispatch_volume_mwh         REAL,
    _raw                        TEXT,
    ingested_at                 TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_nged_disp_tender ON nged_dispatch(tender_reference);
CREATE INDEX IF NOT EXISTS idx_nged_disp_incident ON nged_dispatch(incident_reference);

-- NGED Trade Results Summary
CREATE TABLE IF NOT EXISTS nged_trade_results (
    _id                         INTEGER PRIMARY KEY,
    cmz_code                    TEXT,
    flexibility_product         TEXT,
    trade_opportunity_name      TEXT,
    company_name                TEXT,
    offered_capacity_kw         REAL,
    offered_availability_price  REAL,
    trade_outcome               TEXT,
    accepted_capacity_kw        REAL,
    technology_type             TEXT,
    _raw                        TEXT,
    ingested_at                 TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_nged_trade_cmz ON nged_trade_results(cmz_code);
CREATE INDEX IF NOT EXISTS idx_nged_trade_company ON nged_trade_results(company_name);

-- Raw JSON cache of the full postcode dataset
CREATE TABLE IF NOT EXISTS nged_postcodes_raw (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),
    record_count INTEGER,
    data_json   TEXT NOT NULL
);
"""),
    # -- Migration 3: Portal cache TTL + drift tables --
    (3, """
-- Add expires_at to portal_cache
ALTER TABLE portal_cache ADD COLUMN expires_at TEXT;

-- Drift tracking tables (moved from drift.py)
CREATE TABLE IF NOT EXISTS drift_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portal TEXT NOT NULL,
    dataset TEXT NOT NULL,
    record_count INTEGER,
    field_names TEXT,
    field_hash TEXT,
    sample_prices TEXT,
    snapshot_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS drift_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portal TEXT NOT NULL,
    dataset TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    severity TEXT NOT NULL DEFAULT 'info',
    detected_at TEXT NOT NULL DEFAULT (datetime('now')),
    acknowledged INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_drift_snapshots_portal
    ON drift_snapshots(portal, dataset, snapshot_at);
CREATE INDEX IF NOT EXISTS idx_drift_alerts_unack
    ON drift_alerts(acknowledged, detected_at);
"""),
    # -- Migration 4: Public catalogue registry --
    (4, """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS catalogue_observations (
    observation_id     TEXT PRIMARY KEY,
    portal_id          TEXT NOT NULL,
    observed_at        TEXT NOT NULL,
    content_hash       TEXT NOT NULL,
    snapshot_path      TEXT NOT NULL,
    status             TEXT NOT NULL CHECK (status IN ('complete', 'partial', 'failed')),
    expected_count     INTEGER,
    dataset_count      INTEGER NOT NULL,
    resource_count     INTEGER NOT NULL,
    warnings_json      TEXT NOT NULL DEFAULT '[]',
    raw_pages_json     TEXT NOT NULL DEFAULT '[]',
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (portal_id, observed_at, content_hash)
);

CREATE TABLE IF NOT EXISTS catalogue_datasets (
    dataset_key         TEXT PRIMARY KEY,
    portal_id           TEXT NOT NULL,
    source_dataset_id   TEXT NOT NULL,
    source_record_id    TEXT NOT NULL,
    title               TEXT,
    description         TEXT,
    publisher           TEXT,
    licence             TEXT,
    portal_url          TEXT,
    api_url             TEXT,
    source_created_at   TEXT,
    source_updated_at   TEXT,
    lifecycle_status    TEXT NOT NULL DEFAULT 'unknown',
    publication_pattern TEXT NOT NULL DEFAULT 'unknown',
    access_status       TEXT NOT NULL DEFAULT 'unknown',
    tags_json           TEXT NOT NULL DEFAULT '[]',
    raw_record_json     TEXT NOT NULL DEFAULT '{}',
    first_seen_at       TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL,
    last_observation_id TEXT NOT NULL,
    UNIQUE (portal_id, source_dataset_id),
    FOREIGN KEY (last_observation_id)
        REFERENCES catalogue_observations(observation_id)
);

CREATE TABLE IF NOT EXISTS catalogue_resources (
    resource_key        TEXT PRIMARY KEY,
    dataset_key         TEXT NOT NULL,
    portal_id           TEXT NOT NULL,
    source_dataset_id   TEXT NOT NULL,
    source_resource_id  TEXT NOT NULL,
    name                 TEXT,
    description          TEXT,
    url                  TEXT,
    format               TEXT,
    media_type           TEXT,
    size_bytes           INTEGER,
    source_created_at    TEXT,
    source_updated_at    TEXT,
    raw_record_json      TEXT NOT NULL DEFAULT '{}',
    first_seen_at        TEXT NOT NULL,
    last_seen_at         TEXT NOT NULL,
    last_observation_id  TEXT NOT NULL,
    UNIQUE (portal_id, source_dataset_id, source_resource_id),
    FOREIGN KEY (dataset_key) REFERENCES catalogue_datasets(dataset_key),
    FOREIGN KEY (last_observation_id)
        REFERENCES catalogue_observations(observation_id)
);

CREATE TABLE IF NOT EXISTS classification_evidence (
    evidence_key        TEXT PRIMARY KEY,
    dataset_key         TEXT NOT NULL,
    portal_id           TEXT NOT NULL,
    source_dataset_id   TEXT NOT NULL,
    source_evidence_id  TEXT NOT NULL,
    classification      TEXT NOT NULL,
    evidence             TEXT NOT NULL,
    confidence           TEXT NOT NULL DEFAULT 'unknown',
    source_value_json    TEXT,
    source_url           TEXT,
    observed_at          TEXT,
    raw_record_json      TEXT NOT NULL DEFAULT '{}',
    last_observation_id  TEXT NOT NULL,
    UNIQUE (portal_id, source_dataset_id, source_evidence_id),
    FOREIGN KEY (dataset_key) REFERENCES catalogue_datasets(dataset_key),
    FOREIGN KEY (last_observation_id)
        REFERENCES catalogue_observations(observation_id)
);

CREATE TABLE IF NOT EXISTS catalogue_assessments (
    assessment_id       TEXT PRIMARY KEY,
    dataset_key         TEXT NOT NULL,
    observation_id      TEXT NOT NULL,
    assessment_type     TEXT NOT NULL,
    assessment_value    TEXT NOT NULL,
    confidence          TEXT NOT NULL DEFAULT 'unknown',
    rationale_json      TEXT NOT NULL DEFAULT '[]',
    missing_evidence_json TEXT NOT NULL DEFAULT '[]',
    assessed_at         TEXT NOT NULL,
    UNIQUE (dataset_key, observation_id, assessment_type),
    FOREIGN KEY (dataset_key) REFERENCES catalogue_datasets(dataset_key),
    FOREIGN KEY (observation_id)
        REFERENCES catalogue_observations(observation_id)
);

CREATE INDEX IF NOT EXISTS idx_catalogue_observations_portal_observed
    ON catalogue_observations(portal_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_catalogue_datasets_portal_source
    ON catalogue_datasets(portal_id, source_dataset_id);
CREATE INDEX IF NOT EXISTS idx_catalogue_datasets_last_seen
    ON catalogue_datasets(portal_id, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_catalogue_resources_dataset
    ON catalogue_resources(dataset_key);
CREATE INDEX IF NOT EXISTS idx_classification_evidence_dataset
    ON classification_evidence(dataset_key, classification);
CREATE INDEX IF NOT EXISTS idx_catalogue_assessments_dataset
    ON catalogue_assessments(dataset_key, assessed_at DESC);
INSERT OR IGNORE INTO schema_version (version) VALUES (4);
COMMIT;
"""),
    # -- Migration 5: Additive canonical metadata and cadence fields --
    (5, """
BEGIN IMMEDIATE;
ALTER TABLE catalogue_datasets ADD COLUMN licence_identifier TEXT;
ALTER TABLE catalogue_datasets ADD COLUMN licence_title TEXT;
ALTER TABLE catalogue_datasets ADD COLUMN licence_url TEXT;
ALTER TABLE catalogue_datasets ADD COLUMN attribution TEXT;
ALTER TABLE catalogue_datasets ADD COLUMN themes_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE catalogue_datasets ADD COLUMN catalogue_page_url TEXT;
ALTER TABLE catalogue_datasets ADD COLUMN metadata_api_url TEXT;
ALTER TABLE catalogue_datasets ADD COLUMN declared_update_frequency TEXT;
ALTER TABLE catalogue_datasets ADD COLUMN declared_update_frequency_text TEXT;
INSERT OR IGNORE INTO schema_version (version) VALUES (5);
COMMIT;
"""),
    # -- Migration 6: SSEN NaFIRS HV snapshots and outage evidence --
    (6, """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS source_snapshots (
    snapshot_id          TEXT PRIMARY KEY,
    source_dataset_id    TEXT NOT NULL,
    package_id           TEXT NOT NULL,
    source_resource_id   TEXT NOT NULL,
    licence_area         TEXT NOT NULL CHECK (licence_area IN ('SEPD', 'SHEPD')),
    stable_source_url    TEXT NOT NULL,
    source_modified_at   TEXT,
    fetched_at           TEXT NOT NULL,
    content_sha256       TEXT NOT NULL,
    byte_size            INTEGER NOT NULL,
    row_count            INTEGER NOT NULL,
    observed_columns_json TEXT NOT NULL,
    licence_id           TEXT NOT NULL,
    licence_title        TEXT NOT NULL,
    licence_url          TEXT NOT NULL,
    attribution          TEXT NOT NULL,
    parser_version       TEXT NOT NULL,
    local_snapshot_path  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id               TEXT PRIMARY KEY,
    status               TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    resources_seen       INTEGER NOT NULL,
    snapshots_created    INTEGER NOT NULL DEFAULT 0,
    snapshots_reused     INTEGER NOT NULL DEFAULT 0,
    events_written       INTEGER NOT NULL DEFAULT 0,
    rejects_written      INTEGER NOT NULL DEFAULT 0,
    warnings_json        TEXT NOT NULL DEFAULT '[]',
    error                TEXT,
    started_at           TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at         TEXT
);

CREATE TABLE IF NOT EXISTS outage_events (
    event_id                       TEXT PRIMARY KEY,
    source_dataset_id              TEXT NOT NULL,
    source_resource_id             TEXT NOT NULL,
    source_snapshot_id             TEXT NOT NULL,
    operator                       TEXT NOT NULL,
    licence_area                   TEXT NOT NULL CHECK (licence_area IN ('SEPD', 'SHEPD')),
    incident_started_local         TEXT NOT NULL,
    timezone_name                  TEXT,
    reporting_year                 INTEGER NOT NULL,
    voltage_kv                     REAL,
    district_short_code            TEXT NOT NULL,
    district_hv_reference          TEXT NOT NULL,
    network_reference              TEXT NOT NULL,
    primary_nrn                    TEXT,
    primary_name                   TEXT,
    customers_affected             INTEGER,
    customer_minutes_lost          INTEGER,
    average_minutes_off_supply     REAL,
    equipment_code                 TEXT,
    equipment                      TEXT,
    component_code                 TEXT,
    component                      TEXT,
    cause_code                     TEXT,
    cause                          TEXT,
    contributory_cause_code        TEXT,
    contributory_cause             TEXT,
    damage                         TEXT,
    exceptional_event              TEXT,
    quality_flags_json             TEXT NOT NULL,
    raw_record_json                TEXT NOT NULL,
    FOREIGN KEY (source_snapshot_id)
        REFERENCES source_snapshots(snapshot_id)
);

CREATE TABLE IF NOT EXISTS outage_rejects (
    reject_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                TEXT NOT NULL,
    source_resource_id    TEXT NOT NULL,
    row_number            INTEGER NOT NULL CHECK (row_number >= 1),
    error_code            TEXT NOT NULL,
    error_message         TEXT NOT NULL,
    raw_row_json          TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES ingestion_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_source_snapshots_dataset_resource
    ON source_snapshots(source_dataset_id, source_resource_id);
CREATE INDEX IF NOT EXISTS idx_source_snapshots_fetched
    ON source_snapshots(fetched_at DESC, snapshot_id);
CREATE INDEX IF NOT EXISTS idx_outage_events_area_year
    ON outage_events(licence_area, reporting_year);
CREATE INDEX IF NOT EXISTS idx_outage_events_district
    ON outage_events(district_short_code);
CREATE INDEX IF NOT EXISTS idx_outage_events_cause
    ON outage_events(cause_code);
CREATE INDEX IF NOT EXISTS idx_outage_events_incident
    ON outage_events(incident_started_local, event_id);
CREATE INDEX IF NOT EXISTS idx_outage_rejects_run
    ON outage_rejects(run_id);
INSERT OR IGNORE INTO schema_version (version) VALUES (6);
COMMIT;
"""),
    # -- Migration 7: Immutable outage source and materialisation versions --
    (7, """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS outage_content_blobs (
    content_sha256       TEXT PRIMARY KEY,
    byte_size            INTEGER NOT NULL,
    relative_snapshot_path TEXT,
    available            INTEGER NOT NULL CHECK (available IN (0, 1)),
    CHECK (
        (available = 0 AND relative_snapshot_path IS NULL)
        OR (available = 1 AND relative_snapshot_path IS NOT NULL)
    )
);
CREATE TABLE IF NOT EXISTS outage_source_observations (
    snapshot_id           TEXT PRIMARY KEY,
    source_dataset_id     TEXT NOT NULL,
    package_id            TEXT NOT NULL,
    source_resource_id    TEXT NOT NULL,
    licence_area          TEXT NOT NULL,
    stable_source_url     TEXT NOT NULL,
    content_sha256        TEXT NOT NULL,
    row_count             INTEGER NOT NULL,
    observed_columns_json TEXT NOT NULL,
    licence_id            TEXT NOT NULL,
    licence_title         TEXT NOT NULL,
    licence_url           TEXT NOT NULL,
    attribution           TEXT NOT NULL,
    parser_version        TEXT NOT NULL,
    source_contract_version TEXT NOT NULL,
    canonical_event_schema_version INTEGER NOT NULL,
    FOREIGN KEY (content_sha256)
        REFERENCES outage_content_blobs(content_sha256)
);
CREATE TABLE IF NOT EXISTS outage_event_versions (
    snapshot_id                    TEXT NOT NULL,
    event_id                       TEXT NOT NULL,
    source_resource_id             TEXT NOT NULL,
    licence_area                   TEXT NOT NULL,
    incident_started_local         TEXT NOT NULL,
    reporting_year                 INTEGER NOT NULL,
    voltage_kv                     REAL,
    district_short_code            TEXT NOT NULL,
    equipment_code                 TEXT,
    cause_code                     TEXT,
    customers_affected             INTEGER,
    customer_minutes_lost          INTEGER,
    average_minutes_off_supply     REAL,
    quality_flags_json             TEXT NOT NULL,
    event_json                     TEXT NOT NULL,
    event_sha256                   TEXT NOT NULL,
    canonical_event_schema_version INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, event_id),
    FOREIGN KEY (snapshot_id)
        REFERENCES outage_source_observations(snapshot_id)
);
CREATE TABLE IF NOT EXISTS outage_reject_versions (
    snapshot_id       TEXT NOT NULL,
    reject_id         TEXT NOT NULL,
    source_resource_id TEXT NOT NULL,
    row_number        INTEGER NOT NULL,
    reason_code       TEXT NOT NULL,
    safe_detail_json  TEXT NOT NULL,
    reject_sha256     TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, reject_id),
    FOREIGN KEY (snapshot_id)
        REFERENCES outage_source_observations(snapshot_id)
);
CREATE TABLE IF NOT EXISTS current_outage_snapshots (
    source_resource_id  TEXT PRIMARY KEY,
    snapshot_id         TEXT NOT NULL,
    run_id              TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    FOREIGN KEY (snapshot_id)
        REFERENCES outage_source_observations(snapshot_id),
    FOREIGN KEY (run_id) REFERENCES ingestion_runs(run_id)
);
CREATE TABLE IF NOT EXISTS ingestion_run_snapshots (
    run_id      TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    PRIMARY KEY (run_id, snapshot_id),
    FOREIGN KEY (run_id) REFERENCES ingestion_runs(run_id),
    FOREIGN KEY (snapshot_id)
        REFERENCES outage_source_observations(snapshot_id)
);
CREATE TABLE IF NOT EXISTS outage_fetch_attempts (
    attempt_id         TEXT PRIMARY KEY,
    run_id             TEXT NOT NULL,
    source_resource_id TEXT NOT NULL,
    attempted_at       TEXT NOT NULL,
    status             TEXT NOT NULL,
    response_status    INTEGER,
    source_modified_at TEXT,
    snapshot_id        TEXT,
    content_sha256     TEXT,
    byte_size          INTEGER,
    error_code         TEXT,
    FOREIGN KEY (run_id) REFERENCES ingestion_runs(run_id),
    FOREIGN KEY (snapshot_id)
        REFERENCES outage_source_observations(snapshot_id)
);
CREATE INDEX IF NOT EXISTS idx_outage_observation_resource_content
    ON outage_source_observations(source_resource_id, content_sha256);
CREATE INDEX IF NOT EXISTS idx_outage_event_versions_area_year
    ON outage_event_versions(licence_area, reporting_year);
CREATE INDEX IF NOT EXISTS idx_outage_event_versions_district
    ON outage_event_versions(district_short_code);
CREATE INDEX IF NOT EXISTS idx_outage_event_versions_cause
    ON outage_event_versions(cause_code);
CREATE INDEX IF NOT EXISTS idx_outage_event_versions_incident
    ON outage_event_versions(incident_started_local, event_id);
CREATE INDEX IF NOT EXISTS idx_outage_event_versions_resource
    ON outage_event_versions(source_resource_id, snapshot_id);
CREATE INDEX IF NOT EXISTS idx_outage_event_versions_event_snapshot
    ON outage_event_versions(event_id, snapshot_id);
CREATE INDEX IF NOT EXISTS idx_outage_reject_versions_snapshot_row
    ON outage_reject_versions(snapshot_id, row_number);
CREATE INDEX IF NOT EXISTS idx_ingestion_run_snapshots_run
    ON ingestion_run_snapshots(run_id, snapshot_id);
CREATE INDEX IF NOT EXISTS idx_ingestion_run_snapshots_snapshot
    ON ingestion_run_snapshots(snapshot_id, run_id);
CREATE INDEX IF NOT EXISTS idx_outage_fetch_attempts_run
    ON outage_fetch_attempts(run_id, source_resource_id);
CREATE INDEX IF NOT EXISTS idx_outage_fetch_attempts_snapshot
    ON outage_fetch_attempts(snapshot_id);
CREATE TRIGGER IF NOT EXISTS outage_blob_immutable_update
BEFORE UPDATE ON outage_content_blobs
WHEN NOT (
    OLD.available = 0
    AND OLD.relative_snapshot_path IS NULL
    AND NEW.available = 1
    AND NEW.relative_snapshot_path IS NOT NULL
    AND OLD.content_sha256 = NEW.content_sha256
    AND OLD.byte_size = NEW.byte_size
)
BEGIN
    SELECT RAISE(ABORT, 'outage content blob is immutable');
END;
"""),
]


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _source_snapshot_id(source_resource_id: str, content_sha256: str) -> str:
    return f"ssen-nafirs-hv:{source_resource_id}:sha256:{content_sha256}"


def _backfill_outage_version_seven(conn: sqlite3.Connection) -> None:
    """Backfill only legacy evidence whose snapshot association is provable."""
    legacy_snapshots = conn.execute(
        "SELECT * FROM source_snapshots ORDER BY snapshot_id"
    ).fetchall()
    snapshot_map: dict[str, str] = {}
    for row in legacy_snapshots:
        snapshot_id = _source_snapshot_id(
            row["source_resource_id"], row["content_sha256"]
        )
        snapshot_map[row["snapshot_id"]] = snapshot_id
        blob = conn.execute(
            "SELECT byte_size FROM outage_content_blobs WHERE content_sha256 = ?",
            (row["content_sha256"],),
        ).fetchone()
        if blob is None:
            conn.execute(
                """INSERT INTO outage_content_blobs (
                   content_sha256, byte_size, relative_snapshot_path, available
               ) VALUES (?, ?, NULL, 0)""",
                (row["content_sha256"], row["byte_size"]),
            )
        elif blob["byte_size"] != row["byte_size"]:
            raise sqlite3.IntegrityError(
                "legacy outage blob conflicts with immutable identity"
            )
        observation_values = (
            snapshot_id,
            row["source_dataset_id"],
            row["package_id"],
            row["source_resource_id"],
            row["licence_area"],
            row["stable_source_url"],
            row["content_sha256"],
            row["row_count"],
            _canonical_json(json.loads(row["observed_columns_json"])),
            row["licence_id"],
            row["licence_title"],
            row["licence_url"],
            row["attribution"],
            row["parser_version"],
            "ssen-nafirs-hv-v1",
            1,
        )
        existing = conn.execute(
            "SELECT * FROM outage_source_observations WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if existing is None:
            conn.execute(
                """INSERT INTO outage_source_observations (
                   snapshot_id, source_dataset_id, package_id,
                   source_resource_id, licence_area, stable_source_url,
                   content_sha256, row_count, observed_columns_json,
                   licence_id, licence_title, licence_url, attribution,
                   parser_version, source_contract_version,
                   canonical_event_schema_version
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                observation_values[:-1],
            )
        elif tuple(existing) != observation_values:
            raise sqlite3.IntegrityError(
                "legacy outage observation conflicts with immutable identity"
            )

    for row in conn.execute("SELECT * FROM outage_events ORDER BY event_id"):
        snapshot_id = snapshot_map.get(row["source_snapshot_id"])
        if snapshot_id is None:
            raise sqlite3.IntegrityError(
                "legacy outage event has no provable source snapshot"
            )
        event = dict(row)
        event["source_snapshot_id"] = snapshot_id
        event["quality_flags"] = json.loads(event.pop("quality_flags_json"))
        event["raw_record"] = json.loads(event.pop("raw_record_json"))
        event_json = _canonical_json(event)
        event_sha256 = __import__("hashlib").sha256(event_json.encode()).hexdigest()
        conn.execute(
            """INSERT INTO outage_event_versions (
                   snapshot_id, event_id, source_resource_id, licence_area,
                   incident_started_local, reporting_year, voltage_kv,
                   district_short_code, equipment_code, cause_code,
                   customers_affected, customer_minutes_lost,
                   average_minutes_off_supply, quality_flags_json, event_json,
                   event_sha256, canonical_event_schema_version
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (
                snapshot_id,
                row["event_id"],
                row["source_resource_id"],
                row["licence_area"],
                row["incident_started_local"],
                row["reporting_year"],
                row["voltage_kv"],
                row["district_short_code"],
                row["equipment_code"],
                row["cause_code"],
                row["customers_affected"],
                row["customer_minutes_lost"],
                row["average_minutes_off_supply"],
                _canonical_json(event["quality_flags"]),
                event_json,
                event_sha256,
            ),
        )


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def get_db_path() -> Path:
    """Return the resolved DB path (ensures parent dir exists)."""
    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    return config.db_path


@contextmanager
def get_connection(db_path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for a SQLite connection with WAL mode."""
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_migrations(db_path: Path | None = None) -> int:
    """Apply pending migrations. Returns the new schema version."""
    with get_connection(db_path) as conn:
        # Ensure schema_version table exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version     INTEGER PRIMARY KEY,
                applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_version").fetchall()}

        for version, ddl in MIGRATIONS:
            if version not in applied:
                conn.executescript(ddl)
                if version == 7:
                    _backfill_outage_version_seven(conn)
                conn.execute(
                    "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
                    (version,),
                )
                applied.add(version)

        return max(applied) if applied else 0


# ---------------------------------------------------------------------------
# Portal cache helpers
# ---------------------------------------------------------------------------

def cache_put(
    portal_id: str,
    url: str,
    data: Any,
    etag: str | None = None,
    db_path: Path | None = None,
) -> str:
    """Store a portal API response in the cache. Returns the cache key."""
    import hashlib

    raw = json.dumps(data, ensure_ascii=False, sort_keys=True)
    content_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
    cache_key = f"{portal_id}:{content_hash}"
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()

    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO portal_cache
               (cache_key, portal_id, url, response_json, record_count, etag, content_hash, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cache_key,
                portal_id,
                url,
                raw,
                len(data) if isinstance(data, list) else None,
                etag,
                content_hash,
                expires_at,
            ),
        )
    return cache_key


def cache_get(
    portal_id: str,
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    """Retrieve the most recent cached response for a portal (if not expired)."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            """SELECT response_json, fetched_at, record_count, etag, content_hash, expires_at
               FROM portal_cache WHERE portal_id = ?
               ORDER BY fetched_at DESC LIMIT 1""",
            (portal_id,),
        ).fetchone()
    if row is None:
        return None
    # Check expiration
    if row[5] is not None:
        if datetime.now(timezone.utc).isoformat() > row[5]:
            return None
    return {
        "data": json.loads(row[0]),
        "fetched_at": row[1],
        "record_count": row[2],
        "etag": row[3],
        "content_hash": row[4],
    }


def cache_stats(db_path: Path | None = None) -> list[dict[str, Any]]:
    """Return cache stats per portal, including expired count."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """SELECT portal_id, COUNT(*) as entries,
                      MAX(fetched_at) as last_fetch,
                      SUM(record_count) as total_records,
                      SUM(CASE WHEN expires_at IS NOT NULL
                           AND datetime('now') > expires_at THEN 1 ELSE 0 END) as expired
               FROM portal_cache GROUP BY portal_id"""
        ).fetchall()
    return [dict(row) for row in rows]


def cache_cleanup(db_path: Path | None = None) -> int:
    """Delete expired cache entries. Returns the number of rows deleted."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM portal_cache WHERE expires_at IS NOT NULL AND datetime('now') > expires_at"
        )
        rowcount = cursor.rowcount
    return rowcount

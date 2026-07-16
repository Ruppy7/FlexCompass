"""Behavioural tests for catalogue registry persistence."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pytest
from app.catalogue_adapters import CatalogueFetchResult
from app.catalogue_models import (
    CatalogueDataset,
    ClassificationEvidence,
    DatasetResource,
    EvidenceConfidence,
)
from app.catalogue_store import (
    get_catalogue_dataset,
    latest_catalogue_observation,
    observation_key,
    persist_catalogue_assessment,
    persist_catalogue_result,
)
from app.db import get_connection, run_migrations

OBSERVED_AT = datetime(2026, 7, 16, 8, 30, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "catalogue.db"
    run_migrations(db_path)
    with get_connection(db_path) as connection:
        yield connection


def make_result(
    *,
    portal_id: str = "nged",
    source_dataset_id: str = "shared-source-id",
    complete: bool = True,
    title: str | None = "Public flexibility data",
    resource_url: str | None = "https://example.invalid/public.csv",
    raw_record: dict | None = None,
) -> CatalogueFetchResult:
    dataset_id = f"{portal_id}:{source_dataset_id}"
    resource = DatasetResource(
        id=f"{dataset_id}:resource-one",
        portal_id=portal_id,
        source_dataset_id=source_dataset_id,
        name="Public CSV" if resource_url else None,
        url=resource_url,
        format="CSV" if resource_url else None,
        observed_at=OBSERVED_AT,
        raw_record={"resource_source_only": True} if resource_url else {},
    )
    evidence = ClassificationEvidence(
        id=f"{dataset_id}:access-status",
        portal_id=portal_id,
        source_dataset_id=source_dataset_id,
        classification="access_status",
        evidence="The public API returned a resource URL.",
        confidence=EvidenceConfidence.high,
        source_value={"access": "public"},
        observed_at=OBSERVED_AT,
        raw_record={"evidence_source_only": ["preserve"]},
    )
    dataset = CatalogueDataset(
        id=dataset_id,
        portal_id=portal_id,
        source_dataset_id=source_dataset_id,
        title=title,
        publisher="Synthetic public fixture publisher" if title else None,
        observed_at=OBSERVED_AT,
        tags=["flexibility", "public"] if title else [],
        resources=[resource] if resource_url else [],
        classification_evidence=[evidence] if title else [],
        raw_record=raw_record if raw_record is not None else {"source_dataset_id": source_dataset_id},
    )
    return CatalogueFetchResult(
        portal_id=portal_id,
        observed_at=OBSERVED_AT,
        datasets=[dataset],
        resources=[resource] if resource_url else [],
        expected_count=1 if complete else None,
        complete=complete,
        warnings=[] if complete else ["Pagination total count is absent."],
        raw_pages=[{"result": {"source_dataset_id": source_dataset_id}}],
    )


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_registry_migration_coexists_with_legacy_tables_and_has_foreign_keys_and_indexes(tmp_path):
    db_path = tmp_path / "catalogue.db"

    assert run_migrations(db_path) >= 4

    with get_connection(db_path) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        foreign_keys = {
            table: conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
            for table in (
                "catalogue_datasets",
                "catalogue_resources",
                "classification_evidence",
                "catalogue_assessments",
            )
        }

    assert {
        "portal_datasets",
        "catalogue_observations",
        "catalogue_datasets",
        "catalogue_resources",
        "classification_evidence",
        "catalogue_assessments",
    } <= names
    assert all(foreign_keys.values())
    assert {
        "idx_catalogue_observations_portal_observed",
        "idx_catalogue_datasets_portal_source",
        "idx_catalogue_resources_dataset",
        "idx_classification_evidence_dataset",
        "idx_catalogue_assessments_dataset",
    } <= indexes


def test_observation_identity_is_deterministic_and_portal_scoped():
    first = observation_key("nged", OBSERVED_AT, "abc")

    assert first == observation_key("nged", OBSERVED_AT, "abc")
    assert first != observation_key("spen", OBSERVED_AT, "abc")
    assert first != observation_key("nged", OBSERVED_AT, "def")


def test_reprocessing_same_observation_is_idempotent(conn):
    result = make_result()

    first = persist_catalogue_result(conn, result, "snapshot.json", "abc")
    second = persist_catalogue_result(conn, result, "snapshot.json", "abc")

    assert first == second
    assert first.dataset_count == 1
    assert first.resource_count == 1
    assert count_rows(conn, "catalogue_observations") == 1
    assert count_rows(conn, "catalogue_datasets") == 1
    assert count_rows(conn, "catalogue_resources") == 1
    assert count_rows(conn, "classification_evidence") == 1


def test_persistence_rolls_back_every_table_when_a_resource_write_fails(conn):
    conn.execute(
        """CREATE TRIGGER reject_resource BEFORE INSERT ON catalogue_resources
           BEGIN SELECT RAISE(ABORT, 'synthetic resource failure'); END"""
    )

    with pytest.raises(sqlite3.IntegrityError, match="synthetic resource failure"):
        persist_catalogue_result(conn, make_result(), "snapshot.json", "abc")

    assert count_rows(conn, "catalogue_observations") == 0
    assert count_rows(conn, "catalogue_datasets") == 0
    assert count_rows(conn, "catalogue_resources") == 0
    assert count_rows(conn, "classification_evidence") == 0


def test_incomplete_result_is_rejected_without_explicit_partial_status(conn):
    with pytest.raises(ValueError, match="incomplete"):
        persist_catalogue_result(conn, make_result(complete=False), "snapshot.json", "abc")

    assert count_rows(conn, "catalogue_observations") == 0


def test_incomplete_result_can_be_persisted_with_explicit_partial_status(conn):
    result = persist_catalogue_result(
        conn,
        make_result(complete=False),
        "snapshot.json",
        "abc",
        status="partial",
    )

    observation = latest_catalogue_observation(conn, "nged")
    assert result.dataset_count == 1
    assert observation is not None
    assert observation["status"] == "partial"
    assert observation["warnings"] == ["Pagination total count is absent."]


def test_partial_missing_values_do_not_erase_known_source_facts(conn):
    persist_catalogue_result(conn, make_result(), "complete.json", "complete-hash")

    persist_catalogue_result(
        conn,
        make_result(complete=False, title=None, resource_url=None, raw_record={}),
        "partial.json",
        "partial-hash",
        status="partial",
    )

    dataset = get_catalogue_dataset(conn, "nged", "shared-source-id")
    resource = conn.execute(
        "SELECT name, url, format, raw_record_json FROM catalogue_resources"
    ).fetchone()
    assert dataset is not None
    assert dataset["title"] == "Public flexibility data"
    assert dataset["publisher"] == "Synthetic public fixture publisher"
    assert dataset["tags"] == ["flexibility", "public"]
    assert dataset["raw_record"] == {"source_dataset_id": "shared-source-id"}
    assert tuple(resource[:3]) == (
        "Public CSV",
        "https://example.invalid/public.csv",
        "CSV",
    )
    assert json.loads(resource[3]) == {"resource_source_only": True}


def test_dataset_and_resource_identity_is_scoped_to_portal(conn):
    nged = persist_catalogue_result(conn, make_result(portal_id="nged"), "nged.json", "abc")
    spen = persist_catalogue_result(conn, make_result(portal_id="spen"), "spen.json", "abc")

    assert nged.dataset_count == spen.dataset_count == 1
    assert nged.resource_count == spen.resource_count == 1
    assert count_rows(conn, "catalogue_datasets") == 2
    assert count_rows(conn, "catalogue_resources") == 2
    keys = {
        tuple(row)
        for row in conn.execute(
            "SELECT portal_id, source_dataset_id FROM catalogue_datasets ORDER BY portal_id"
        )
    }
    assert keys == {("nged", "shared-source-id"), ("spen", "shared-source-id")}


def test_structured_and_raw_provenance_round_trip_as_json(conn):
    persist_catalogue_result(conn, make_result(), "snapshot.json", "abc")

    dataset = get_catalogue_dataset(conn, "nged", "shared-source-id")
    evidence = conn.execute(
        "SELECT source_value_json, raw_record_json FROM classification_evidence"
    ).fetchone()
    observation = latest_catalogue_observation(conn, "nged")

    assert dataset is not None
    assert dataset["tags"] == ["flexibility", "public"]
    assert dataset["raw_record"] == {"source_dataset_id": "shared-source-id"}
    assert json.loads(evidence[0]) == {"access": "public"}
    assert json.loads(evidence[1]) == {"evidence_source_only": ["preserve"]}
    assert observation is not None
    assert observation["raw_pages"] == [
        {"result": {"source_dataset_id": "shared-source-id"}}
    ]


def test_catalogue_assessment_persistence_is_idempotent_and_json_preserving(conn):
    persisted = persist_catalogue_result(conn, make_result(), "snapshot.json", "abc")
    values = {
        "assessment_id": "nged:shared-source-id:maintenance",
        "portal_id": "nged",
        "source_dataset_id": "shared-source-id",
        "observation_id": persisted.observation_id,
        "assessment_type": "maintenance_state",
        "assessment_value": "unknown",
        "confidence": "unknown",
        "rationale": ["Missing evidence; no schedule was inferred."],
        "missing_evidence": ["published update schedule"],
        "assessed_at": OBSERVED_AT,
    }

    persist_catalogue_assessment(conn, **values)
    persist_catalogue_assessment(conn, **values)

    row = conn.execute(
        "SELECT rationale_json, missing_evidence_json FROM catalogue_assessments"
    ).fetchone()
    assert count_rows(conn, "catalogue_assessments") == 1
    assert json.loads(row[0]) == values["rationale"]
    assert json.loads(row[1]) == values["missing_evidence"]

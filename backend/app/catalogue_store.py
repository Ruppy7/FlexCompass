"""Transactional SQLite persistence for public catalogue observations."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from app.catalogue_adapters import CatalogueFetchResult
from app.catalogue_models import CatalogueDataset, ClassificationEvidence, DatasetResource

ObservationStatus = Literal["complete", "partial", "failed"]


@dataclass(frozen=True)
class PersistResult:
    """Counts and stable identity for one persisted fetch observation."""

    observation_id: str
    dataset_count: int
    resource_count: int


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("catalogue timestamps must include a timezone")
    return value.astimezone(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def observation_key(portal_id: str, observed_at: datetime, content_hash: str) -> str:
    """Return the deterministic identity of a portal fetch observation."""
    observed = _timestamp(observed_at)
    digest = hashlib.sha256(f"{portal_id}\n{observed}\n{content_hash}".encode()).hexdigest()
    return f"{portal_id}:{digest}"


def _dataset_key(portal_id: str, source_dataset_id: str) -> str:
    return f"{portal_id}:{source_dataset_id}"


def _resource_key(resource: DatasetResource) -> str:
    return f"{resource.portal_id}:{resource.source_dataset_id}:{resource.id}"


def _evidence_key(evidence: ClassificationEvidence) -> str:
    return f"{evidence.portal_id}:{evidence.source_dataset_id}:{evidence.id}"


def _upsert_observation(
    conn: sqlite3.Connection,
    observation_id: str,
    result: CatalogueFetchResult,
    snapshot_path: str,
    content_hash: str,
    status: ObservationStatus,
) -> None:
    conn.execute(
        """INSERT INTO catalogue_observations (
               observation_id, portal_id, observed_at, content_hash, snapshot_path,
               status, expected_count, dataset_count, resource_count,
               warnings_json, raw_pages_json
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(observation_id) DO UPDATE SET
               snapshot_path = excluded.snapshot_path,
               status = excluded.status,
               expected_count = COALESCE(excluded.expected_count, expected_count),
               dataset_count = excluded.dataset_count,
               resource_count = excluded.resource_count,
               warnings_json = excluded.warnings_json,
               raw_pages_json = excluded.raw_pages_json""",
        (
            observation_id,
            result.portal_id,
            _timestamp(result.observed_at),
            content_hash,
            snapshot_path,
            status,
            result.expected_count,
            len(result.datasets),
            len(result.resources),
            _json(list(result.warnings)),
            _json(list(result.raw_pages)),
        ),
    )


def _upsert_dataset(
    conn: sqlite3.Connection,
    observation_id: str,
    dataset: CatalogueDataset,
    preserve_missing: bool,
) -> None:
    dataset_key = _dataset_key(dataset.portal_id, dataset.source_dataset_id)
    observed_at = _timestamp(dataset.observed_at)
    nullable_fields = (
        "title",
        "description",
        "publisher",
        "licence",
        "portal_url",
        "api_url",
        "source_created_at",
        "source_updated_at",
        "licence_identifier",
        "licence_title",
        "licence_url",
        "attribution",
        "catalogue_page_url",
        "metadata_api_url",
        "declared_update_frequency",
        "declared_update_frequency_text",
    )
    nullable_updates = ",\n               ".join(
        f"{field} = "
        + (
            f"COALESCE(excluded.{field}, {field})"
            if preserve_missing
            else f"excluded.{field}"
        )
        for field in nullable_fields
    )
    if preserve_missing:
        state_updates = """lifecycle_status = CASE
                   WHEN excluded.lifecycle_status = 'unknown' THEN lifecycle_status
                   ELSE excluded.lifecycle_status END,
               publication_pattern = CASE
                   WHEN excluded.publication_pattern = 'unknown' THEN publication_pattern
                   ELSE excluded.publication_pattern END,
               access_status = CASE
                   WHEN excluded.access_status = 'unknown' THEN access_status
                   ELSE excluded.access_status END,
               tags_json = CASE
                   WHEN excluded.tags_json = '[]' THEN tags_json
                   ELSE excluded.tags_json END,
               raw_record_json = CASE
                   WHEN excluded.raw_record_json = '{}' THEN raw_record_json
                   ELSE excluded.raw_record_json END,
               themes_json = CASE
                   WHEN excluded.themes_json = '[]' THEN themes_json
                   ELSE excluded.themes_json END"""
    else:
        state_updates = """lifecycle_status = excluded.lifecycle_status,
               publication_pattern = excluded.publication_pattern,
               access_status = excluded.access_status,
               tags_json = excluded.tags_json,
               raw_record_json = excluded.raw_record_json,
               themes_json = excluded.themes_json"""
    conn.execute(
        f"""INSERT INTO catalogue_datasets (
               dataset_key, portal_id, source_dataset_id, source_record_id, title,
               description, publisher, licence, portal_url, api_url,
               source_created_at, source_updated_at, lifecycle_status,
               publication_pattern, access_status, tags_json, raw_record_json,
               first_seen_at, last_seen_at, last_observation_id,
               licence_identifier, licence_title, licence_url, attribution,
               themes_json, catalogue_page_url, metadata_api_url,
               declared_update_frequency, declared_update_frequency_text
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(dataset_key) DO UPDATE SET
               source_record_id = excluded.source_record_id,
               {nullable_updates},
               {state_updates},
               last_seen_at = excluded.last_seen_at,
               last_observation_id = excluded.last_observation_id""",
        (
            dataset_key,
            dataset.portal_id,
            dataset.source_dataset_id,
            dataset.id,
            dataset.title,
            dataset.description,
            dataset.publisher,
            dataset.licence,
            dataset.portal_url,
            dataset.api_url,
            _timestamp(dataset.source_created_at),
            _timestamp(dataset.source_updated_at),
            dataset.lifecycle_status.value,
            dataset.publication_pattern.value,
            dataset.access_status.value,
            _json(dataset.tags),
            _json(dataset.raw_record),
            observed_at,
            observed_at,
            observation_id,
            dataset.licence_identifier,
            dataset.licence_title,
            dataset.licence_url,
            dataset.attribution,
            _json(dataset.themes),
            dataset.catalogue_page_url,
            dataset.metadata_api_url,
            dataset.declared_update_frequency,
            dataset.declared_update_frequency_text,
        ),
    )


def _upsert_resource(
    conn: sqlite3.Connection,
    observation_id: str,
    resource: DatasetResource,
    observed_at: datetime,
    preserve_missing: bool,
) -> None:
    seen_at = _timestamp(resource.observed_at or observed_at)
    nullable_fields = (
        "name",
        "description",
        "url",
        "format",
        "media_type",
        "size_bytes",
        "source_created_at",
        "source_updated_at",
    )
    nullable_updates = ",\n               ".join(
        f"{field} = "
        + (
            f"COALESCE(excluded.{field}, {field})"
            if preserve_missing
            else f"excluded.{field}"
        )
        for field in nullable_fields
    )
    raw_update = (
        "CASE WHEN excluded.raw_record_json = '{}' "
        "THEN raw_record_json ELSE excluded.raw_record_json END"
        if preserve_missing
        else "excluded.raw_record_json"
    )
    conn.execute(
        f"""INSERT INTO catalogue_resources (
               resource_key, dataset_key, portal_id, source_dataset_id,
               source_resource_id, name, description, url, format, media_type,
               size_bytes, source_created_at, source_updated_at, raw_record_json,
               first_seen_at, last_seen_at, last_observation_id
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(resource_key) DO UPDATE SET
               source_resource_id = excluded.source_resource_id,
               {nullable_updates},
               raw_record_json = {raw_update},
               last_seen_at = excluded.last_seen_at,
               last_observation_id = excluded.last_observation_id""",
        (
            _resource_key(resource),
            _dataset_key(resource.portal_id, resource.source_dataset_id),
            resource.portal_id,
            resource.source_dataset_id,
            resource.id,
            resource.name,
            resource.description,
            resource.url,
            resource.format,
            resource.media_type,
            resource.size_bytes,
            _timestamp(resource.source_created_at),
            _timestamp(resource.source_updated_at),
            _json(resource.raw_record),
            seen_at,
            seen_at,
            observation_id,
        ),
    )


def _upsert_evidence(
    conn: sqlite3.Connection,
    observation_id: str,
    evidence: ClassificationEvidence,
    preserve_missing: bool,
) -> None:
    source_value_json = None if evidence.source_value is None else _json(evidence.source_value)
    if preserve_missing:
        evidence_updates = """confidence = CASE
                   WHEN excluded.confidence = 'unknown' THEN confidence
                   ELSE excluded.confidence END,
               source_value_json = COALESCE(excluded.source_value_json, source_value_json),
               source_url = COALESCE(excluded.source_url, source_url),
               observed_at = COALESCE(excluded.observed_at, observed_at),
               raw_record_json = CASE
                   WHEN excluded.raw_record_json = '{}' THEN raw_record_json
                   ELSE excluded.raw_record_json END"""
    else:
        evidence_updates = """confidence = excluded.confidence,
               source_value_json = excluded.source_value_json,
               source_url = excluded.source_url,
               observed_at = excluded.observed_at,
               raw_record_json = excluded.raw_record_json"""
    conn.execute(
        f"""INSERT INTO classification_evidence (
               evidence_key, dataset_key, portal_id, source_dataset_id,
               source_evidence_id, classification, evidence, confidence,
               source_value_json, source_url, observed_at, raw_record_json,
               last_observation_id
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(evidence_key) DO UPDATE SET
               classification = excluded.classification,
               evidence = excluded.evidence,
               {evidence_updates},
               last_observation_id = excluded.last_observation_id""",
        (
            _evidence_key(evidence),
            _dataset_key(evidence.portal_id, evidence.source_dataset_id),
            evidence.portal_id,
            evidence.source_dataset_id,
            evidence.id,
            evidence.classification,
            evidence.evidence,
            evidence.confidence.value,
            source_value_json,
            evidence.source_url,
            _timestamp(evidence.observed_at),
            _json(evidence.raw_record),
            observation_id,
        ),
    )


def _validate_result_associations(result: CatalogueFetchResult) -> None:
    """Validate the complete nested provenance graph before any database write."""
    datasets: dict[str, CatalogueDataset] = {}
    nested_resource_keys: set[str] = set()
    for dataset in result.datasets:
        if dataset.portal_id != result.portal_id:
            raise ValueError("dataset association portal does not match fetch result")
        if dataset.source_dataset_id in datasets:
            raise ValueError("duplicate dataset association in fetch result")
        datasets[dataset.source_dataset_id] = dataset
        seen_evidence: set[str] = set()
        for resource in dataset.resources:
            if (
                resource.portal_id != dataset.portal_id
                or resource.source_dataset_id != dataset.source_dataset_id
            ):
                raise ValueError("nested resource association does not match parent dataset")
            key = _resource_key(resource)
            if key in nested_resource_keys:
                raise ValueError("duplicate nested resource association in fetch result")
            nested_resource_keys.add(key)
        for evidence in dataset.classification_evidence:
            if (
                evidence.portal_id != dataset.portal_id
                or evidence.source_dataset_id != dataset.source_dataset_id
            ):
                raise ValueError("nested evidence association does not match parent dataset")
            key = _evidence_key(evidence)
            if key in seen_evidence:
                raise ValueError("duplicate nested evidence association in fetch result")
            seen_evidence.add(key)

    top_level_resource_keys: set[str] = set()
    for resource in result.resources:
        if resource.portal_id != result.portal_id:
            raise ValueError("resource association portal does not match fetch result")
        if resource.source_dataset_id not in datasets:
            raise ValueError("resource must belong to a dataset in the same fetch result")
        key = _resource_key(resource)
        if key in top_level_resource_keys:
            raise ValueError("duplicate top-level resource association in fetch result")
        top_level_resource_keys.add(key)
    if nested_resource_keys != top_level_resource_keys:
        raise ValueError("nested and top-level resource associations must match")


def persist_catalogue_result(
    conn: sqlite3.Connection,
    result: CatalogueFetchResult,
    snapshot_path: str,
    content_hash: str,
    *,
    status: ObservationStatus | None = None,
) -> PersistResult:
    """Persist one fetch atomically, rejecting implicit partial observations."""
    effective_status: ObservationStatus = status or "complete"
    if not result.complete and status not in {"partial", "failed"}:
        raise ValueError("incomplete catalogue results require explicit partial or failed status")
    if effective_status not in {"complete", "partial", "failed"}:
        raise ValueError(f"unsupported catalogue observation status: {effective_status}")

    _validate_result_associations(result)
    observation_id = observation_key(result.portal_id, result.observed_at, content_hash)
    preserve_missing = effective_status == "partial"
    conn.execute("SAVEPOINT persist_catalogue_result")
    try:
        _upsert_observation(conn, observation_id, result, snapshot_path, content_hash, effective_status)
        if effective_status == "failed":
            conn.execute("RELEASE SAVEPOINT persist_catalogue_result")
            return PersistResult(
                observation_id,
                len(result.datasets),
                len(result.resources),
            )
        for dataset in result.datasets:
            _upsert_dataset(conn, observation_id, dataset, preserve_missing)
        for resource in result.resources:
            _upsert_resource(conn, observation_id, resource, result.observed_at, preserve_missing)
        for dataset in result.datasets:
            for evidence in dataset.classification_evidence:
                _upsert_evidence(conn, observation_id, evidence, preserve_missing)
        if effective_status == "complete":
            for dataset in result.datasets:
                dataset_key = _dataset_key(
                    dataset.portal_id,
                    dataset.source_dataset_id,
                )
                conn.execute(
                    """DELETE FROM catalogue_resources
                       WHERE dataset_key = ? AND last_observation_id <> ?""",
                    (dataset_key, observation_id),
                )
                conn.execute(
                    """DELETE FROM classification_evidence
                       WHERE dataset_key = ? AND last_observation_id <> ?""",
                    (dataset_key, observation_id),
                )
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT persist_catalogue_result")
        conn.execute("RELEASE SAVEPOINT persist_catalogue_result")
        raise
    conn.execute("RELEASE SAVEPOINT persist_catalogue_result")
    return PersistResult(observation_id, len(result.datasets), len(result.resources))


def persist_catalogue_assessment(
    conn: sqlite3.Connection,
    *,
    assessment_id: str,
    portal_id: str,
    source_dataset_id: str,
    observation_id: str,
    assessment_type: str,
    assessment_value: str,
    confidence: str,
    rationale: list[str],
    missing_evidence: list[str],
    assessed_at: datetime,
) -> None:
    """Idempotently store one evidence-led catalogue assessment."""
    dataset_key = _dataset_key(portal_id, source_dataset_id)
    existing = conn.execute(
        "SELECT dataset_key FROM catalogue_assessments WHERE assessment_id = ?",
        (assessment_id,),
    ).fetchone()
    if existing is not None and existing[0] != dataset_key:
        raise ValueError("assessment_id is already associated with another dataset")
    observation = conn.execute(
        "SELECT portal_id FROM catalogue_observations WHERE observation_id = ?",
        (observation_id,),
    ).fetchone()
    if observation is not None and observation[0] != portal_id:
        raise ValueError("assessment observation portal does not match dataset portal")
    conn.execute(
        """INSERT INTO catalogue_assessments (
               assessment_id, dataset_key, observation_id, assessment_type,
               assessment_value, confidence, rationale_json,
               missing_evidence_json, assessed_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(assessment_id) DO UPDATE SET
               observation_id = excluded.observation_id,
               assessment_type = excluded.assessment_type,
               assessment_value = excluded.assessment_value,
               confidence = excluded.confidence,
               rationale_json = excluded.rationale_json,
               missing_evidence_json = excluded.missing_evidence_json,
               assessed_at = excluded.assessed_at""",
        (
            assessment_id,
            dataset_key,
            observation_id,
            assessment_type,
            assessment_value,
            confidence,
            _json(rationale),
            _json(missing_evidence),
            _timestamp(assessed_at),
        ),
    )


def _decoded_row(row: sqlite3.Row | tuple[Any, ...] | None, columns: list[str]) -> dict[str, Any] | None:
    if row is None:
        return None
    record = dict(row) if isinstance(row, sqlite3.Row) else dict(zip(columns, row, strict=True))
    for key in tuple(record):
        if key.endswith("_json"):
            value = record.pop(key)
            record[key.removesuffix("_json")] = None if value is None else json.loads(value)
    return record


def get_catalogue_dataset(
    conn: sqlite3.Connection, portal_id: str, source_dataset_id: str
) -> dict[str, Any] | None:
    """Return one current dataset with JSON fields decoded."""
    cursor = conn.execute(
        "SELECT * FROM catalogue_datasets WHERE portal_id = ? AND source_dataset_id = ?",
        (portal_id, source_dataset_id),
    )
    return _decoded_row(cursor.fetchone(), [item[0] for item in cursor.description])


def list_catalogue_datasets(
    conn: sqlite3.Connection, portal_id: str | None = None
) -> list[dict[str, Any]]:
    """Return current catalogue datasets, optionally scoped to one portal."""
    if portal_id is None:
        cursor = conn.execute("SELECT * FROM catalogue_datasets ORDER BY portal_id, source_dataset_id")
    else:
        cursor = conn.execute(
            "SELECT * FROM catalogue_datasets WHERE portal_id = ? ORDER BY source_dataset_id",
            (portal_id,),
        )
    columns = [item[0] for item in cursor.description]
    return [_decoded_row(row, columns) for row in cursor.fetchall()]


def list_catalogue_resources(
    conn: sqlite3.Connection, portal_id: str, source_dataset_id: str
) -> list[dict[str, Any]]:
    """Return a portal dataset's resources with raw provenance decoded."""
    cursor = conn.execute(
        """SELECT * FROM catalogue_resources
           WHERE portal_id = ? AND source_dataset_id = ?
           ORDER BY resource_key""",
        (portal_id, source_dataset_id),
    )
    columns = [item[0] for item in cursor.description]
    return [_decoded_row(row, columns) for row in cursor.fetchall()]


def list_classification_evidence(
    conn: sqlite3.Connection, portal_id: str, source_dataset_id: str
) -> list[dict[str, Any]]:
    """Return stored evidence for one portal dataset with JSON decoded."""
    cursor = conn.execute(
        """SELECT * FROM classification_evidence
           WHERE portal_id = ? AND source_dataset_id = ?
           ORDER BY evidence_key""",
        (portal_id, source_dataset_id),
    )
    columns = [item[0] for item in cursor.description]
    return [_decoded_row(row, columns) for row in cursor.fetchall()]


def list_catalogue_assessments(
    conn: sqlite3.Connection, portal_id: str, source_dataset_id: str
) -> list[dict[str, Any]]:
    """Return stored assessments for one portal dataset with JSON decoded."""
    cursor = conn.execute(
        """SELECT assessment.* FROM catalogue_assessments AS assessment
           JOIN catalogue_datasets AS dataset
             ON dataset.dataset_key = assessment.dataset_key
           WHERE dataset.portal_id = ? AND dataset.source_dataset_id = ?
           ORDER BY assessment.assessed_at, assessment.assessment_id""",
        (portal_id, source_dataset_id),
    )
    columns = [item[0] for item in cursor.description]
    return [_decoded_row(row, columns) for row in cursor.fetchall()]


def latest_catalogue_observation(
    conn: sqlite3.Connection, portal_id: str
) -> dict[str, Any] | None:
    """Return the most recent observation for a portal with JSON decoded."""
    cursor = conn.execute(
        """SELECT * FROM catalogue_observations
           WHERE portal_id = ? ORDER BY observed_at DESC, created_at DESC LIMIT 1""",
        (portal_id,),
    )
    return _decoded_row(cursor.fetchone(), [item[0] for item in cursor.description])

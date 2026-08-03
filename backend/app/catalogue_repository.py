"""Read-only repository over validated immutable catalogue snapshots."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from app.catalogue_models import (
    CatalogueDataset,
    ClassificationEvidence,
    DatasetResource,
    PortalId,
)
from app.catalogue_snapshot import CatalogueSnapshot, load_catalogue_snapshot
from app.catalogue_store import (
    catalogue_assessment_key,
    list_catalogue_assessments_for_observation,
)
from app.db import get_connection

ReviewStatus = Literal["current", "overdue", "never_attempted"]


@dataclass(frozen=True)
class PortalState:
    portal_id: str
    current_attempt_status: str | None
    current_attempt_at: datetime | None
    current_attempt_warning_count: int
    current_attempt_safe_error: str | None
    review_due_at: datetime | None
    review_status: ReviewStatus
    last_complete_observation_id: str | None
    last_complete_observed_at: datetime | None
    latest_complete_snapshot_valid: bool | None
    latest_complete_validation_state: Literal["valid", "invalid", "unavailable"]
    last_valid_observation_id: str | None
    last_valid_observed_at: datetime | None
    last_valid_dataset_count: int
    last_valid_resource_count: int
    degraded: bool
    snapshot_available: bool


@dataclass(frozen=True)
class CatalogueObservationRecord:
    observation_id: str
    portal_id: str
    observed_at: datetime
    status: str
    adapter_version: str | None
    schema_version: int | None
    content_hash: str | None
    expected_count: int | None
    dataset_count: int | None
    resource_count: int | None
    complete: bool | None


def _timestamp(value: object | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("catalogue repository timestamp must be text")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("catalogue repository timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _safe_timestamp(value: object | None) -> datetime | None:
    """Project unvalidated display metadata without defeating fallback."""
    try:
        return _timestamp(value)
    except (TypeError, ValueError):
        return None


class CatalogueRepository:
    """Select last-valid evidence without consulting mutable registry rows."""

    def __init__(
        self,
        *,
        db_path: Path,
        snapshot_root: Path,
        review_window_hours: int = 168,
    ) -> None:
        self.db_path = db_path
        self.snapshot_root = snapshot_root
        self.review_window_hours = review_window_hours

    @staticmethod
    def _complete_rows(
        connection: sqlite3.Connection,
        portal_id: str,
    ) -> list[sqlite3.Row]:
        return connection.execute(
            """SELECT observation_id, portal_id, observed_at, content_hash,
                      snapshot_path, dataset_count, resource_count
               FROM catalogue_observations
               WHERE portal_id = ? AND status = 'complete'
               ORDER BY observed_at DESC, created_at DESC, observation_id DESC""",
            (portal_id,),
        ).fetchall()

    def _load_row(self, row: sqlite3.Row) -> CatalogueSnapshot:
        snapshot = load_catalogue_snapshot(
            Path(row["snapshot_path"]),
            snapshot_root=self.snapshot_root,
            expected_portal_id=row["portal_id"],
            expected_content_hash=row["content_hash"],
        )
        if snapshot.observation_id != row["observation_id"]:
            raise ValueError("snapshot identity does not match observation")
        if snapshot.observed_at != _timestamp(row["observed_at"]):
            raise ValueError("snapshot timestamp does not match observation")
        if (
            len(snapshot.datasets) != row["dataset_count"]
            or len(snapshot.resources) != row["resource_count"]
        ):
            raise ValueError("snapshot counts do not match observation")
        return snapshot

    def load_complete_observation(
        self,
        portal_id: PortalId,
        observation_id: str,
    ) -> CatalogueSnapshot:
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                """SELECT observation_id, portal_id, observed_at, content_hash,
                          snapshot_path, dataset_count, resource_count
                   FROM catalogue_observations
                   WHERE portal_id = ? AND observation_id = ?
                     AND status = 'complete'""",
                (portal_id, observation_id),
            ).fetchone()
        if row is None:
            raise LookupError("complete catalogue observation not found")
        return self._load_row(row)

    def _last_valid(self, portal_id: str) -> tuple[sqlite3.Row, CatalogueSnapshot] | None:
        with get_connection(self.db_path) as connection:
            rows = self._complete_rows(connection, portal_id)
        for row in rows:
            try:
                return row, self._load_row(row)
            except (OSError, ValueError):
                continue
        return None

    def portal_state(self, portal_id: PortalId, *, now: datetime) -> PortalState:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must include a timezone")
        now_utc = now.astimezone(timezone.utc)
        with get_connection(self.db_path) as connection:
            attempt = connection.execute(
                """SELECT status, attempted_at, warning_count, safe_error
                   FROM catalogue_refresh_attempts
                   WHERE portal_id = ?
                   ORDER BY attempted_at DESC, created_at DESC, attempt_id DESC
                   LIMIT 1""",
                (portal_id,),
            ).fetchone()
            complete_rows = self._complete_rows(connection, portal_id)

        latest_complete = complete_rows[0] if complete_rows else None
        last_valid_row: sqlite3.Row | None = None
        last_valid_snapshot: CatalogueSnapshot | None = None
        latest_valid: bool | None = None
        for index, row in enumerate(complete_rows):
            try:
                loaded = self._load_row(row)
            except (OSError, ValueError):
                if index == 0:
                    latest_valid = False
                continue
            if index == 0:
                latest_valid = True
            last_valid_row = row
            last_valid_snapshot = loaded
            break

        attempted_at = _timestamp(attempt["attempted_at"]) if attempt else None
        review_due_at = (
            attempted_at + timedelta(hours=self.review_window_hours)
            if attempted_at is not None
            else None
        )
        review_status: ReviewStatus
        if review_due_at is None:
            review_status = "never_attempted"
        elif now_utc > review_due_at:
            review_status = "overdue"
        else:
            review_status = "current"
        degraded = bool(
            latest_complete is not None
            and last_valid_row is not None
            and latest_complete["observation_id"]
            != last_valid_row["observation_id"]
        )
        return PortalState(
            portal_id=portal_id,
            current_attempt_status=attempt["status"] if attempt else None,
            current_attempt_at=attempted_at,
            current_attempt_warning_count=attempt["warning_count"] if attempt else 0,
            current_attempt_safe_error=attempt["safe_error"] if attempt else None,
            review_due_at=review_due_at,
            review_status=review_status,
            last_complete_observation_id=(
                latest_complete["observation_id"] if latest_complete else None
            ),
            last_complete_observed_at=(
                _safe_timestamp(latest_complete["observed_at"])
                if latest_complete
                else None
            ),
            latest_complete_snapshot_valid=latest_valid,
            latest_complete_validation_state=(
                "unavailable"
                if latest_complete is None
                else "valid"
                if latest_valid
                else "invalid"
            ),
            last_valid_observation_id=(
                last_valid_snapshot.observation_id if last_valid_snapshot else None
            ),
            last_valid_observed_at=(
                last_valid_snapshot.observed_at if last_valid_snapshot else None
            ),
            last_valid_dataset_count=(
                len(last_valid_snapshot.datasets) if last_valid_snapshot else 0
            ),
            last_valid_resource_count=(
                len(last_valid_snapshot.resources) if last_valid_snapshot else 0
            ),
            degraded=degraded,
            snapshot_available=last_valid_snapshot is not None,
        )

    def _last_valid_snapshot(self, portal_id: str) -> CatalogueSnapshot | None:
        selected = self._last_valid(portal_id)
        return selected[1] if selected else None

    def list_last_valid_datasets(
        self,
        portal_id: PortalId,
    ) -> tuple[CatalogueDataset, ...]:
        snapshot = self._last_valid_snapshot(portal_id)
        return snapshot.datasets if snapshot else ()

    def get_last_valid_dataset(
        self,
        portal_id: PortalId,
        source_dataset_id: str,
    ) -> CatalogueDataset | None:
        return next(
            (
                dataset
                for dataset in self.list_last_valid_datasets(portal_id)
                if dataset.source_dataset_id == source_dataset_id
            ),
            None,
        )

    def list_last_valid_resources(
        self,
        portal_id: PortalId,
        source_dataset_id: str,
    ) -> tuple[DatasetResource, ...]:
        snapshot = self._last_valid_snapshot(portal_id)
        if snapshot is None:
            return ()
        return tuple(
            item
            for item in snapshot.resources
            if item.source_dataset_id == source_dataset_id
        )

    def list_last_valid_evidence(
        self,
        portal_id: PortalId,
        source_dataset_id: str,
    ) -> tuple[ClassificationEvidence, ...]:
        snapshot = self._last_valid_snapshot(portal_id)
        if snapshot is None:
            return ()
        return tuple(
            item
            for item in snapshot.evidence
            if item.source_dataset_id == source_dataset_id
        )

    def list_last_valid_assessments(
        self,
        portal_id: PortalId,
        source_dataset_id: str,
    ) -> tuple[dict[str, object], ...]:
        snapshot = self._last_valid_snapshot(portal_id)
        if snapshot is None:
            return ()
        if not any(
            dataset.source_dataset_id == source_dataset_id
            for dataset in snapshot.datasets
        ):
            return ()
        with get_connection(self.db_path) as connection:
            rows = list_catalogue_assessments_for_observation(
                connection,
                portal_id,
                source_dataset_id,
                snapshot.observation_id,
            )
        return tuple(
            row
            for row in rows
            if row["assessment_id"]
            == catalogue_assessment_key(
                portal_id,
                source_dataset_id,
                snapshot.observation_id,
                str(row["assessment_type"]),
            )
        )

    def list_observations(
        self,
        portal_id: PortalId | None = None,
    ) -> tuple[CatalogueObservationRecord, ...]:
        """Return deterministic safe observation history without local metadata."""
        query = """SELECT observation_id, portal_id, observed_at, status,
                          content_hash, expected_count, dataset_count, resource_count
                   FROM catalogue_observations"""
        parameters: tuple[str, ...] = ()
        if portal_id is not None:
            query += " WHERE portal_id = ?"
            parameters = (portal_id,)
        query += " ORDER BY observed_at DESC, created_at DESC, observation_id DESC"
        with get_connection(self.db_path) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(
            CatalogueObservationRecord(
                observation_id=row["observation_id"],
                portal_id=row["portal_id"],
                observed_at=_timestamp(row["observed_at"]),  # type: ignore[arg-type]
                status=row["status"],
                adapter_version=None,
                schema_version=None,
                content_hash=row["content_hash"],
                expected_count=row["expected_count"],
                dataset_count=row["dataset_count"],
                resource_count=row["resource_count"],
                complete=row["status"] == "complete",
            )
            for row in rows
        )

"""Behavioural tests for immutable catalogue snapshot queries."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from app.catalogue_adapters import CatalogueFetchResult
from app.catalogue_models import (
    CatalogueDataset,
    ClassificationEvidence,
    DatasetResource,
    EvidenceConfidence,
)
from app.catalogue_repository import CatalogueRepository
from app.catalogue_snapshot import load_catalogue_snapshot
from app.catalogue_store import (
    catalogue_assessment_key,
    observation_key,
    persist_catalogue_assessment,
    persist_catalogue_result,
    record_catalogue_refresh_attempt,
)
from app.catalogue_sync import _canonical_json, _snapshot_identity
from app.db import get_connection, run_migrations

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def _dataset(
    source_id: str,
    observed_at: datetime,
    *,
    evidence_ids: tuple[str, ...] = (),
) -> CatalogueDataset:
    resource = DatasetResource(
        id=f"resource-{source_id}",
        portal_id="nged",
        source_dataset_id=source_id,
        name=f"Resource {source_id}",
        url=f"https://example.invalid/{source_id}.csv",
        observed_at=observed_at,
    )
    evidence = [
        ClassificationEvidence(
            id=evidence_id,
            portal_id="nged",
            source_dataset_id=source_id,
            classification="access_status",
            evidence=f"Evidence {evidence_id}",
            confidence=EvidenceConfidence.high,
            observed_at=observed_at,
        )
        for evidence_id in evidence_ids
    ]
    return CatalogueDataset(
        id=f"nged:{source_id}",
        portal_id="nged",
        source_dataset_id=source_id,
        title=f"Dataset {source_id}",
        observed_at=observed_at,
        resources=[resource],
        classification_evidence=evidence,
        raw_record={"source_dataset_id": source_id},
    )


def _write_snapshot(
    root: Path,
    name: str,
    observed_at: datetime,
    datasets: tuple[CatalogueDataset, ...],
    *,
    complete: bool = True,
) -> tuple[Path, str, CatalogueFetchResult]:
    resources = tuple(
        resource for dataset in datasets for resource in dataset.resources
    )
    raw_pages = ({"result": {"count": len(datasets)}},)
    core = {
        "datasets": [item.model_dump(mode="json") for item in datasets],
        "resources": [item.model_dump(mode="json") for item in resources],
        "raw_pages": list(raw_pages),
    }
    content_hash = hashlib.sha256(
        _canonical_json(_snapshot_identity(core))
    ).hexdigest()
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "manifest": {
                    "adapter_version": "1",
                    "schema_version": 1,
                    "portal_id": "nged",
                    "portal_status": "complete" if complete else "partial",
                    "observed_at": observed_at.isoformat(),
                    "dataset_count": len(datasets),
                    "resource_count": len(resources),
                    "expected_count": len(datasets) if complete else len(datasets) + 1,
                    "complete": complete,
                    "content_hash": content_hash,
                    "snapshot_path": path.as_posix(),
                },
                **core,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    result = CatalogueFetchResult(
        portal_id="nged",
        observed_at=observed_at,
        datasets=list(datasets),
        resources=list(resources),
        expected_count=len(datasets) if complete else len(datasets) + 1,
        complete=complete,
        warnings=[] if complete else ["Incomplete public pagination evidence."],
        raw_pages=list(raw_pages),
    )
    return path, content_hash, result


def _persist_snapshot(
    db_path: Path,
    path: Path,
    content_hash: str,
    result: CatalogueFetchResult,
    *,
    status: str,
) -> str:
    with get_connection(db_path) as connection:
        persisted = persist_catalogue_result(
            connection,
            result,
            path.as_posix(),
            content_hash,
            status=status,
        )
        record_catalogue_refresh_attempt(
            connection,
            portal_id="nged",
            attempted_at=result.observed_at,
            status=status,
            observation_id=persisted.observation_id,
            warnings=result.warnings,
            safe_error_text=None,
        )
    return persisted.observation_id


def _repository_with_two_complete_snapshots(
    tmp_path: Path,
) -> tuple[CatalogueRepository, Path, str, str]:
    db_path = tmp_path / "registry.sqlite3"
    snapshot_root = tmp_path / "snapshots"
    run_migrations(db_path)
    older_at = NOW - timedelta(days=2)
    newest_at = NOW - timedelta(days=1)
    older_path, older_hash, older_result = _write_snapshot(
        snapshot_root,
        "older/nged.json",
        older_at,
        (_dataset("older", older_at),),
    )
    newest_path, newest_hash, newest_result = _write_snapshot(
        snapshot_root,
        "newest/nged.json",
        newest_at,
        (_dataset("newest", newest_at),),
    )
    older_id = _persist_snapshot(
        db_path, older_path, older_hash, older_result, status="complete"
    )
    newest_id = _persist_snapshot(
        db_path, newest_path, newest_hash, newest_result, status="complete"
    )
    return (
        CatalogueRepository(db_path=db_path, snapshot_root=snapshot_root),
        newest_path,
        older_id,
        newest_id,
    )


def test_snapshot_loader_rejects_path_outside_root(tmp_path: Path) -> None:
    outside, content_hash, _ = _write_snapshot(
        tmp_path,
        "outside.json",
        NOW,
        (_dataset("outside", NOW),),
    )
    approved = tmp_path / "approved"
    approved.mkdir()

    with pytest.raises(ValueError, match="snapshot root"):
        load_catalogue_snapshot(
            outside,
            snapshot_root=approved,
            expected_portal_id="nged",
            expected_content_hash=content_hash,
        )


def test_snapshot_loader_rejects_symlink_escape(tmp_path: Path) -> None:
    outside_dir = tmp_path / "outside"
    outside, content_hash, _ = _write_snapshot(
        outside_dir,
        "snapshot.json",
        NOW,
        (_dataset("outside", NOW),),
    )
    approved = tmp_path / "approved"
    approved.mkdir()
    if os.name == "nt":
        link = approved / "junction"
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside_dir)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(f"local junction creation unavailable: {result.stderr}")
        candidate = link / "snapshot.json"
    else:
        link = approved / "linked.json"
        os.symlink(outside, link)
        candidate = link

    with pytest.raises(ValueError, match="snapshot root"):
        load_catalogue_snapshot(
            candidate,
            snapshot_root=approved,
            expected_portal_id="nged",
            expected_content_hash=content_hash,
        )


def test_snapshot_loader_orders_datasets_resources_and_nested_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "snapshots"
    path, content_hash, _ = _write_snapshot(
        root,
        "nged.json",
        NOW,
        (
            _dataset("zeta", NOW, evidence_ids=("z-two", "z-one")),
            _dataset("alpha", NOW, evidence_ids=("a-two", "a-one")),
        ),
    )

    snapshot = load_catalogue_snapshot(
        path,
        snapshot_root=root,
        expected_portal_id="nged",
        expected_content_hash=content_hash,
    )

    assert [item.source_dataset_id for item in snapshot.datasets] == [
        "alpha",
        "zeta",
    ]
    assert [item.source_dataset_id for item in snapshot.resources] == [
        "alpha",
        "zeta",
    ]
    assert [item.id for item in snapshot.evidence] == [
        "a-one",
        "a-two",
        "z-one",
        "z-two",
    ]
    assert snapshot.observation_id == observation_key("nged", NOW, content_hash)


@pytest.mark.parametrize("defect", ["association", "duplicate"])
def test_snapshot_loader_rejects_invalid_nested_evidence(
    tmp_path: Path,
    defect: str,
) -> None:
    root = tmp_path / "snapshots"
    dataset = _dataset("alpha", NOW, evidence_ids=("evidence-one",))
    evidence = dataset.classification_evidence[0]
    if defect == "association":
        dataset.classification_evidence[0] = evidence.model_copy(
            update={"source_dataset_id": "other"}
        )
    else:
        dataset.classification_evidence.append(evidence.model_copy())
    path, content_hash, _ = _write_snapshot(
        root,
        "nged.json",
        NOW,
        (dataset,),
    )

    with pytest.raises(ValueError, match="evidence association|evidence identity"):
        load_catalogue_snapshot(
            path,
            snapshot_root=root,
            expected_portal_id="nged",
            expected_content_hash=content_hash,
        )


@pytest.mark.parametrize("status", ["partial", "failed"])
def test_partial_or_failed_refresh_does_not_replace_last_complete_snapshot(
    tmp_path: Path,
    status: str,
) -> None:
    repository, _, _, complete_id = _repository_with_two_complete_snapshots(
        tmp_path
    )
    if status == "partial":
        partial_path, partial_hash, partial_result = _write_snapshot(
            repository.snapshot_root,
            "partial/nged.json",
            NOW,
            (_dataset("partial", NOW),),
            complete=False,
        )
        _persist_snapshot(
            repository.db_path,
            partial_path,
            partial_hash,
            partial_result,
            status="partial",
        )
    else:
        with get_connection(repository.db_path) as connection:
            record_catalogue_refresh_attempt(
                connection,
                portal_id="nged",
                attempted_at=NOW,
                status="failed",
                observation_id=None,
                warnings=(),
                safe_error_text="RuntimeError: operation failed",
            )

    state = repository.portal_state("nged", now=NOW)

    assert state.current_attempt_status == status
    assert state.last_complete_observation_id == complete_id
    assert [
        item.source_dataset_id
        for item in repository.list_last_valid_datasets("nged")
    ] == ["newest"]


def test_invalid_newest_complete_falls_back_to_older_valid_snapshot(
    tmp_path: Path,
) -> None:
    repository, newest_path, older_id, newest_id = (
        _repository_with_two_complete_snapshots(tmp_path)
    )
    newest_path.write_text("{corrupt", encoding="utf-8")

    state = repository.portal_state("nged", now=NOW)

    assert state.last_complete_observation_id == newest_id
    assert state.latest_complete_snapshot_valid is False
    assert state.degraded is True
    assert state.last_valid_observation_id == older_id
    assert [
        item.source_dataset_id
        for item in repository.list_last_valid_datasets("nged")
    ] == ["older"]


def test_blob_snapshot_path_preserves_older_valid_snapshot(
    tmp_path: Path,
) -> None:
    repository, _, older_id, newest_id = (
        _repository_with_two_complete_snapshots(tmp_path)
    )
    with get_connection(repository.db_path) as connection:
        connection.execute(
            """UPDATE catalogue_observations SET snapshot_path = ?
               WHERE observation_id = ?""",
            (sqlite3.Binary(b"not-a-text-path"), newest_id),
        )

    state = repository.portal_state("nged", now=NOW)

    assert state.last_complete_observation_id == newest_id
    assert state.latest_complete_validation_state == "invalid"
    assert state.last_valid_observation_id == older_id
    assert state.snapshot_available is True
    assert [
        item.source_dataset_id
        for item in repository.list_last_valid_datasets("nged")
    ] == ["older"]


@pytest.mark.parametrize(
    "malformed_attempted_at",
    [
        pytest.param("", id="empty-text"),
        pytest.param(" ", id="whitespace-text"),
        pytest.param("zz-not-a-timestamp", id="text"),
        pytest.param(sqlite3.Binary(b"not-a-timestamp"), id="blob"),
    ],
)
def test_malformed_latest_attempt_is_absent_without_relabelling_older_attempt(
    tmp_path: Path,
    malformed_attempted_at: object,
) -> None:
    repository, _, _, newest_id = _repository_with_two_complete_snapshots(tmp_path)
    with get_connection(repository.db_path) as connection:
        connection.execute(
            """UPDATE catalogue_refresh_attempts SET attempted_at = ?
               WHERE attempted_at = ?""",
            (malformed_attempted_at, (NOW - timedelta(days=1)).isoformat()),
        )

    state = repository.portal_state("nged", now=NOW)

    assert state.current_attempt_status is None
    assert state.current_attempt_at is None
    assert state.current_attempt_warning_count == 0
    assert state.current_attempt_safe_error is None
    assert state.review_due_at is None
    assert state.review_status == "never_attempted"
    assert state.last_valid_observation_id == newest_id
    assert state.snapshot_available is True


def test_valid_historical_backfill_does_not_replace_chronologically_latest_attempt(
    tmp_path: Path,
) -> None:
    repository, _, _, _ = _repository_with_two_complete_snapshots(tmp_path)
    with get_connection(repository.db_path) as connection:
        record_catalogue_refresh_attempt(
            connection,
            portal_id="nged",
            attempted_at=NOW - timedelta(days=3),
            status="failed",
            observation_id=None,
            warnings=(),
            safe_error_text="Historical failure.",
        )

    state = repository.portal_state("nged", now=NOW)

    assert state.current_attempt_status == "complete"
    assert state.current_attempt_at == NOW - timedelta(days=1)


def test_more_than_one_thousand_backfills_preserve_chronological_current_attempt(
    tmp_path: Path,
) -> None:
    repository, _, _, _ = _repository_with_two_complete_snapshots(tmp_path)
    with get_connection(repository.db_path) as connection:
        for seconds in range(1000):
            record_catalogue_refresh_attempt(
                connection,
                portal_id="nged",
                attempted_at=NOW - timedelta(days=10, seconds=seconds),
                status="failed",
                observation_id=None,
                warnings=(),
                safe_error_text="Historical backfill.",
            )

    state = repository.portal_state("nged", now=NOW)

    assert state.current_attempt_status == "complete"
    assert state.current_attempt_at == NOW - timedelta(days=1)


def test_later_valid_append_restores_current_attempt_after_malformed_row(
    tmp_path: Path,
) -> None:
    repository, _, _, _ = _repository_with_two_complete_snapshots(tmp_path)
    with get_connection(repository.db_path) as connection:
        connection.execute(
            """UPDATE catalogue_refresh_attempts SET attempted_at = ''
               WHERE attempted_at = ?""",
            ((NOW - timedelta(days=1)).isoformat(),),
        )
        record_catalogue_refresh_attempt(
            connection,
            portal_id="nged",
            attempted_at=NOW,
            status="failed",
            observation_id=None,
            warnings=("One warning.",),
            safe_error_text="Latest safe failure.",
        )

    state = repository.portal_state("nged", now=NOW)

    assert state.current_attempt_status == "failed"
    assert state.current_attempt_at == NOW
    assert state.current_attempt_warning_count == 1
    assert state.current_attempt_safe_error == "Latest safe failure."
    assert state.review_status == "current"


def test_all_complete_snapshots_invalid_is_unavailable_without_mutable_fallback(
    tmp_path: Path,
) -> None:
    repository, newest_path, _, _ = _repository_with_two_complete_snapshots(
        tmp_path
    )
    newest_path.write_text("{corrupt", encoding="utf-8")
    for candidate in repository.snapshot_root.rglob("*.json"):
        candidate.write_text("{corrupt", encoding="utf-8")

    state = repository.portal_state("nged", now=NOW)

    assert state.snapshot_available is False
    assert state.last_valid_observation_id is None
    assert repository.list_last_valid_datasets("nged") == ()
    assert repository.get_last_valid_dataset("nged", "newest") is None


def test_load_complete_observation_validates_the_named_snapshot(
    tmp_path: Path,
) -> None:
    repository, newest_path, older_id, newest_id = (
        _repository_with_two_complete_snapshots(tmp_path)
    )
    newest_path.write_text("{corrupt", encoding="utf-8")

    assert repository.load_complete_observation(
        "nged", older_id
    ).observation_id == older_id
    with pytest.raises(ValueError):
        repository.load_complete_observation("nged", newest_id)
    with pytest.raises(LookupError):
        repository.load_complete_observation("nged", "missing")


def test_public_snapshot_loader_rejects_partial_manifest(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    path, content_hash, _ = _write_snapshot(
        root,
        "partial.json",
        NOW,
        (_dataset("partial", NOW),),
        complete=False,
    )

    with pytest.raises(ValueError, match="not complete"):
        load_catalogue_snapshot(
            path,
            snapshot_root=root,
            expected_portal_id="nged",
            expected_content_hash=content_hash,
        )


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("observed_at", NOW.isoformat(), "timestamp"),
        ("dataset_count", 99, "counts"),
        ("resource_count", 99, "counts"),
    ],
)
def test_named_complete_rejects_db_observation_identity_drift(
    tmp_path: Path,
    column: str,
    value: object,
    message: str,
) -> None:
    repository, _, _, newest_id = _repository_with_two_complete_snapshots(
        tmp_path
    )
    with get_connection(repository.db_path) as connection:
        connection.execute(
            f"UPDATE catalogue_observations SET {column} = ? "
            "WHERE observation_id = ?",
            (value, newest_id),
        )

    with pytest.raises(ValueError, match=message):
        repository.load_complete_observation("nged", newest_id)


def test_legacy_assessment_id_is_not_relabelled_as_snapshot_truth(
    tmp_path: Path,
) -> None:
    repository, _, _, newest_id = _repository_with_two_complete_snapshots(
        tmp_path
    )
    with get_connection(repository.db_path) as connection:
        persist_catalogue_assessment(
            connection,
            assessment_id="nged:newest:maintenance",
            portal_id="nged",
            source_dataset_id="newest",
            observation_id=newest_id,
            assessment_type="maintenance",
            assessment_value="unknown",
            confidence="unknown",
            rationale=["Legacy derived row."],
            missing_evidence=["fresh observation-specific assessment"],
            assessed_at=NOW,
        )

    assert repository.list_last_valid_assessments("nged", "newest") == ()


@pytest.mark.parametrize(
    "malformed_observed_at",
    [
        pytest.param("not-a-timestamp", id="text"),
        pytest.param(sqlite3.Binary(b"not-a-timestamp"), id="blob"),
    ],
)
def test_malformed_newest_observation_metadata_preserves_older_fallback(
    tmp_path: Path,
    malformed_observed_at: object,
) -> None:
    repository, _, older_id, newest_id = (
        _repository_with_two_complete_snapshots(tmp_path)
    )
    with get_connection(repository.db_path) as connection:
        connection.execute(
            """UPDATE catalogue_observations SET observed_at = ?
               WHERE observation_id = ?""",
            (malformed_observed_at, newest_id),
        )

    state = repository.portal_state("nged", now=NOW)

    assert state.last_complete_observation_id == newest_id
    assert state.last_complete_observed_at is None
    assert state.latest_complete_snapshot_valid is False
    assert state.last_valid_observation_id == older_id
    assert state.degraded is True
    assert state.snapshot_available is True


def test_assessments_exclude_mutable_only_dataset_absent_from_snapshot(
    tmp_path: Path,
) -> None:
    repository, _, _, newest_id = _repository_with_two_complete_snapshots(
        tmp_path
    )
    partial_path, partial_hash, partial_result = _write_snapshot(
        repository.snapshot_root,
        "partial/phantom.json",
        NOW,
        (_dataset("phantom", NOW),),
        complete=False,
    )
    _persist_snapshot(
        repository.db_path,
        partial_path,
        partial_hash,
        partial_result,
        status="partial",
    )
    with get_connection(repository.db_path) as connection:
        persist_catalogue_assessment(
            connection,
            assessment_id=catalogue_assessment_key(
                "nged",
                "phantom",
                newest_id,
                "maintenance",
            ),
            portal_id="nged",
            source_dataset_id="phantom",
            observation_id=newest_id,
            assessment_type="maintenance",
            assessment_value="unknown",
            confidence="unknown",
            rationale=["Mutable-only derived row."],
            missing_evidence=["immutable dataset membership"],
            assessed_at=NOW,
        )

    assert repository.get_last_valid_dataset("nged", "phantom") is None
    assert repository.list_last_valid_assessments("nged", "phantom") == ()

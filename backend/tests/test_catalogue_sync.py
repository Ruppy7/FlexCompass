"""Behavioural tests for safe catalogue sync orchestration and CLI helpers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import app.catalogue_sync as catalogue_sync
import pytest
from app.catalogue_adapters import CatalogueFetchResult
from app.catalogue_models import (
    CATALOGUE_PORTALS,
    AccessStatus,
    CatalogueDataset,
    ClassificationEvidence,
    DatasetResource,
    EvidenceConfidence,
)
from app.catalogue_sync import diff_snapshots, sync_catalogues
from app.db import get_connection, run_migrations

NOW = datetime(2026, 7, 16, 8, 9, 10, tzinfo=timezone.utc)


def make_result(
    portal_id: str,
    *,
    source_id: str = "public-dataset",
    title: str = "Public dataset",
    access: AccessStatus = AccessStatus.unknown,
    resource_url: str = "https://example.invalid/public.csv",
    complete: bool = True,
    raw_record: dict[str, Any] | None = None,
) -> CatalogueFetchResult:
    evidence = ClassificationEvidence(
        id=f"{portal_id}:{source_id}:access",
        portal_id=portal_id,
        source_dataset_id=source_id,
        classification="access_status",
        evidence="Public metadata access label.",
        source_value=access.value if access is not AccessStatus.unknown else None,
        confidence=EvidenceConfidence.high if access is not AccessStatus.unknown else EvidenceConfidence.unknown,
        observed_at=NOW,
    )
    resource = DatasetResource(
        id=f"{portal_id}:resource-one",
        portal_id=portal_id,
        source_dataset_id=source_id,
        name="CSV",
        url=resource_url,
        format="CSV",
        observed_at=NOW,
        raw_record={"url": resource_url},
    )
    dataset = CatalogueDataset(
        id=f"{portal_id}:{source_id}",
        portal_id=portal_id,
        source_dataset_id=source_id,
        title=title,
        observed_at=NOW,
        access_status=access,
        resources=[resource],
        classification_evidence=[evidence],
        raw_record=raw_record or {"name": source_id},
    )
    return CatalogueFetchResult(
        portal_id=portal_id,
        observed_at=NOW,
        datasets=[dataset],
        resources=[resource],
        expected_count=1 if complete else 2,
        complete=complete,
        warnings=[] if complete else ["Pagination evidence is incomplete."],
        raw_pages=[{"result": {"records": [raw_record or {"name": source_id}]}}],
    )


class FakeClient:
    def __init__(self, portal_id: str, results: dict[str, CatalogueFetchResult | Exception]) -> None:
        self.portal_id = portal_id
        self.results = results

    def close(self) -> None:
        return None


def fake_fetch(portal, client: FakeClient, observed_at: datetime) -> CatalogueFetchResult:
    outcome = client.results[client.portal_id]
    if isinstance(outcome, Exception):
        raise outcome
    return outcome


def run_sync(tmp_path: Path, results: dict[str, CatalogueFetchResult | Exception]):
    db_path = tmp_path / "catalogue.sqlite3"
    run_migrations(db_path)
    return sync_catalogues(
        list(results),
        lambda portal: FakeClient(
            next(portal_id for portal_id, registered in CATALOGUE_PORTALS.items() if registered is portal),
            results,
        ),
        db_path,
        tmp_path / "snapshots",
        NOW,
        fetcher=fake_fetch,
        review_queue_path=tmp_path / "cache" / "review-queue.json",
        policy_path=Path(__file__).parents[2] / "data" / "catalogue" / "maintenance-policy.json",
    )


def test_one_failed_portal_does_not_block_successful_portal_or_overwrite_registry(tmp_path: Path):
    initial = run_sync(tmp_path, {"nged": make_result("nged", title="Last valid title")})
    summary = run_sync(
        tmp_path,
        {
            "nged": RuntimeError("synthetic-secret"),
            "spen": make_result("spen"),
        },
    )

    assert initial.status == "complete"
    assert summary.status == "partial"
    assert summary.exit_code == 2
    assert summary.portals["nged"].status == "failed"
    assert "synthetic-secret" not in (summary.portals["nged"].error or "")
    assert summary.portals["spen"].status == "complete"
    with get_connection(tmp_path / "catalogue.sqlite3") as conn:
        title = conn.execute(
            "SELECT title FROM catalogue_datasets WHERE portal_id = 'nged'"
        ).fetchone()[0]
    assert title == "Last valid title"
    queue = json.loads(summary.review_queue_path.read_text(encoding="utf-8"))
    assert {item["portal_id"] for item in queue} == {"nged", "spen"}


@pytest.mark.parametrize(
    ("results", "status", "exit_code"),
    [
        ({"nged": make_result("nged")}, "complete", 0),
        ({"nged": make_result("nged", complete=False)}, "partial", 2),
        ({"nged": RuntimeError("offline")}, "failed", 1),
    ],
)
def test_sync_summary_status_and_exit_semantics(tmp_path: Path, results, status: str, exit_code: int):
    summary = run_sync(tmp_path, results)
    assert summary.status == status
    assert summary.exit_code == exit_code


def test_snapshot_is_canonical_atomic_redacted_and_repeatable(tmp_path: Path):
    unsafe = {
        "name": "public-dataset",
        "authorization": "Bearer synthetic-secret",
        "api_key": "synthetic-secret",
        "url": "https://user:pass@10.0.0.8/data?token=synthetic-secret&safe=yes",
    }
    first = run_sync(tmp_path, {"nged": make_result("nged", raw_record=unsafe)})
    second = run_sync(tmp_path, {"nged": make_result("nged", raw_record=unsafe)})
    outcome = first.portals["nged"]
    text = outcome.snapshot_path.read_text(encoding="utf-8")
    payload = json.loads(text)

    assert outcome.content_hash == second.portals["nged"].content_hash
    assert outcome.snapshot_path == second.portals["nged"].snapshot_path
    assert "synthetic-secret" not in text
    assert "Bearer" not in text
    assert "10.0.0.8" not in text
    assert not list(outcome.snapshot_path.parent.glob("*.tmp"))
    assert {
        "adapter_version": "1",
        "schema_version": 1,
        "portal_id": "nged",
        "portal_status": "complete",
        "dataset_count": 1,
        "resource_count": 1,
        "complete": True,
        "content_hash": outcome.content_hash,
    }.items() <= payload["manifest"].items()
    assert payload["manifest"]["snapshot_path"].endswith("/nged.json")
    assert payload["manifest"]["observed_at"] == "2026-07-16T08:09:10+00:00"
    with get_connection(tmp_path / "catalogue.sqlite3") as conn:
        stored_raw = conn.execute(
            "SELECT raw_record_json FROM catalogue_datasets WHERE portal_id = 'nged'"
        ).fetchone()[0]
    assert "synthetic-secret" not in stored_raw
    assert "10.0.0.8" not in stored_raw


def test_sync_rejects_resource_collections_that_diff_would_reject(tmp_path: Path):
    result = make_result("nged")
    result.datasets[0].resources = [
        result.resources[0].model_copy(update={"name": "Nested-only name"})
    ]

    summary = run_sync(tmp_path, {"nged": result})

    assert summary.status == "failed"
    assert summary.portals["nged"].snapshot_path is None
    assert not list((tmp_path / "snapshots").rglob("nged.json"))


def test_content_hash_ignores_observation_clock_for_identical_source_content(tmp_path: Path):
    first = run_sync(tmp_path, {"nged": make_result("nged")})
    later = NOW + timedelta(minutes=5)
    original = make_result("nged")
    resources = [item.model_copy(update={"observed_at": later}) for item in original.resources]
    datasets = [
        item.model_copy(update={"observed_at": later, "resources": resources})
        for item in original.datasets
    ]
    repeated = CatalogueFetchResult(
        portal_id="nged",
        observed_at=later,
        datasets=datasets,
        resources=resources,
        expected_count=original.expected_count,
        complete=True,
        warnings=original.warnings,
        raw_pages=original.raw_pages,
    )
    db_path = tmp_path / "catalogue.sqlite3"
    second = sync_catalogues(
        ["nged"],
        lambda portal: FakeClient("nged", {"nged": repeated}),
        db_path,
        tmp_path / "snapshots",
        later,
        fetcher=fake_fetch,
        review_queue_path=tmp_path / "cache" / "review-queue.json",
        policy_path=Path(__file__).parents[2] / "data" / "catalogue" / "maintenance-policy.json",
    )

    assert first.portals["nged"].content_hash == second.portals["nged"].content_hash


def test_content_hash_preserves_source_observation_clocks_in_raw_provenance(tmp_path: Path):
    first = run_sync(
        tmp_path,
        {"nged": make_result("nged", raw_record={"name": "public-dataset", "observed_at": "source-one"})},
    )
    later = NOW + timedelta(minutes=5)
    changed_source = make_result(
        "nged",
        raw_record={"name": "public-dataset", "observed_at": "source-two"},
    )
    second = sync_catalogues(
        ["nged"],
        lambda portal: FakeClient("nged", {"nged": changed_source}),
        tmp_path / "catalogue.sqlite3",
        tmp_path / "snapshots",
        later,
        fetcher=fake_fetch,
        review_queue_path=tmp_path / "cache" / "review-queue.json",
        policy_path=Path(__file__).parents[2] / "data" / "catalogue" / "maintenance-policy.json",
    )

    assert first.portals["nged"].content_hash != second.portals["nged"].content_hash


def write_snapshot(
    path: Path,
    *datasets: CatalogueDataset,
    portal_id: str | None = None,
    complete: bool = True,
) -> Path:
    resolved_portal = portal_id or (
        datasets[0].portal_id if datasets else "nged"
    )
    resources = [
        resource.model_dump(mode="json")
        for dataset in datasets
        for resource in dataset.resources
    ]
    core = {
        "datasets": [item.model_dump(mode="json") for item in datasets],
        "resources": resources,
        "raw_pages": [],
    }
    content_hash = hashlib.sha256(
        catalogue_sync._canonical_json(
            catalogue_sync._snapshot_identity(core)
        )
    ).hexdigest()
    path.write_text(
        json.dumps(
            {
                "manifest": {
                    "adapter_version": "1",
                    "schema_version": 1,
                    "portal_id": resolved_portal,
                    "portal_status": "complete" if complete else "partial",
                    "dataset_count": len(datasets),
                    "resource_count": len(resources),
                    "expected_count": len(datasets) if complete else len(datasets) + 1,
                    "complete": complete,
                    "content_hash": content_hash,
                },
                **core,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def test_diff_reports_dataset_metadata_resource_and_access_changes(tmp_path: Path):
    removed = make_result("nged", source_id="removed").datasets[0]
    changed_before = make_result("nged", title="Old", access=AccessStatus.unknown).datasets[0]
    changed_after = make_result(
        "nged", title="New", access=AccessStatus.public, resource_url="https://example.invalid/new.csv"
    ).datasets[0]
    added = make_result("nged", source_id="added").datasets[0]
    before = write_snapshot(tmp_path / "before.json", removed, changed_before)
    after = write_snapshot(tmp_path / "after.json", changed_after, added)

    result = diff_snapshots(before, after)

    assert {(change.kind, change.source_dataset_id) for change in result.changes} == {
        ("dataset_added", "added"),
        ("dataset_removed", "removed"),
        ("metadata_changed", "public-dataset"),
        ("source_evidence_changed", "public-dataset"),
        ("resources_replaced", "public-dataset"),
        ("access_changed", "public-dataset"),
    }
    assert diff_snapshots(after, after).changes == ()


def test_diff_ignores_generated_resource_observation_clocks(tmp_path: Path):
    before_dataset = make_result("nged").datasets[0]
    later = NOW + timedelta(minutes=5)
    later_resources = [resource.model_copy(update={"observed_at": later}) for resource in before_dataset.resources]
    after_dataset = before_dataset.model_copy(update={"observed_at": later, "resources": later_resources})

    before = write_snapshot(tmp_path / "before.json", before_dataset)
    after = write_snapshot(tmp_path / "after.json", after_dataset)

    assert diff_snapshots(before, after).changes == ()


def test_diff_rejects_snapshots_from_different_portals(tmp_path: Path):
    before = write_snapshot(tmp_path / "before.json", make_result("nged").datasets[0])
    after = write_snapshot(tmp_path / "after.json", make_result("spen").datasets[0])

    with pytest.raises(ValueError, match="different portals"):
        diff_snapshots(before, after)


def test_diff_compares_complete_canonical_metadata_and_raw_schema_evidence(
    tmp_path: Path,
):
    before_dataset = make_result("nged").datasets[0]
    before_dataset.licence_identifier = "old-id"
    before_dataset.licence_title = "Old licence"
    before_dataset.licence_url = "https://example.invalid/old-licence"
    before_dataset.attribution = "Old attribution"
    before_dataset.themes = ["old-theme"]
    before_dataset.catalogue_page_url = "https://example.invalid/old-page"
    before_dataset.metadata_api_url = "https://example.invalid/old-api"
    before_dataset.declared_update_frequency = "weekly"
    before_dataset.declared_update_frequency_text = "Weekly"
    before_dataset.source_updated_at = NOW - timedelta(days=1)
    before_dataset.raw_record = {"schema": {"fields": ["old-field"]}}
    after_dataset = before_dataset.model_copy(deep=True)
    after_dataset.licence_identifier = "new-id"
    after_dataset.licence_title = "New licence"
    after_dataset.licence_url = "https://example.invalid/new-licence"
    after_dataset.attribution = "New attribution"
    after_dataset.themes = ["new-theme"]
    after_dataset.catalogue_page_url = "https://example.invalid/new-page"
    after_dataset.metadata_api_url = "https://example.invalid/new-api"
    after_dataset.declared_update_frequency = "annual"
    after_dataset.declared_update_frequency_text = "Annual"
    after_dataset.source_updated_at = NOW
    after_dataset.raw_record = {"schema": {"fields": ["new-field"]}}

    result = diff_snapshots(
        write_snapshot(tmp_path / "before.json", before_dataset),
        write_snapshot(tmp_path / "after.json", after_dataset),
    )

    changes = {change.kind: change for change in result.changes}
    assert {"metadata_changed", "source_evidence_changed"} <= changes.keys()
    assert set(changes["metadata_changed"].before) == {
        "title",
        "description",
        "publisher",
        "licence",
        "licence_identifier",
        "licence_title",
        "licence_url",
        "attribution",
        "themes",
        "catalogue_page_url",
        "metadata_api_url",
        "declared_update_frequency",
        "declared_update_frequency_text",
        "portal_url",
        "api_url",
        "source_created_at",
        "source_updated_at",
        "lifecycle_status",
        "publication_pattern",
        "tags",
    }
    assert changes["source_evidence_changed"].before["raw_record"] == {
        "schema": {"fields": ["old-field"]}
    }


def test_diff_does_not_report_definitive_removal_from_partial_snapshot(
    tmp_path: Path,
):
    before = write_snapshot(
        tmp_path / "before.json",
        make_result("nged", source_id="possibly-present").datasets[0],
    )
    after = write_snapshot(
        tmp_path / "after.json",
        portal_id="nged",
        complete=False,
    )

    result = diff_snapshots(before, after)

    assert not any(change.kind == "dataset_removed" for change in result.changes)


def test_diff_does_not_report_definitive_addition_from_partial_baseline(
    tmp_path: Path,
):
    before = write_snapshot(
        tmp_path / "before.json",
        portal_id="nged",
        complete=False,
    )
    after = write_snapshot(
        tmp_path / "after.json",
        make_result("nged", source_id="possibly-existing").datasets[0],
    )

    result = diff_snapshots(before, after)

    assert not any(change.kind == "dataset_added" for change in result.changes)


def test_diff_compares_resources_and_evidence_order_insensitively(tmp_path: Path):
    first = make_result("nged").datasets[0]
    second_resource = first.resources[0].model_copy(
        update={
            "id": "nged:resource-two",
            "name": "JSON",
            "url": "https://example.invalid/public.json",
            "format": "JSON",
        }
    )
    first.resources.append(second_resource)
    second_evidence = first.classification_evidence[0].model_copy(
        update={"id": "nged:public-dataset:access-two"}
    )
    first.classification_evidence.append(second_evidence)
    reordered = first.model_copy(deep=True)
    reordered.resources.reverse()
    reordered.classification_evidence.reverse()

    result = diff_snapshots(
        write_snapshot(tmp_path / "before.json", first),
        write_snapshot(tmp_path / "after.json", reordered),
    )

    assert result.changes == ()


@pytest.mark.parametrize(
    ("manifest_field", "invalid_value", "message"),
    [
        ("schema_version", 999, "schema version"),
        ("content_hash", "not-the-content-hash", "content hash"),
    ],
)
def test_diff_rejects_invalid_snapshot_semantics(
    tmp_path: Path,
    manifest_field: str,
    invalid_value,
    message: str,
):
    before = write_snapshot(
        tmp_path / "before.json",
        make_result("nged").datasets[0],
    )
    after = write_snapshot(
        tmp_path / "after.json",
        make_result("nged").datasets[0],
    )
    payload = json.loads(after.read_text(encoding="utf-8"))
    payload["manifest"][manifest_field] = invalid_value
    after.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        diff_snapshots(before, after)


def test_review_queue_contains_only_stable_evidence_led_unresolved_cases(tmp_path: Path):
    summary = run_sync(tmp_path, {"nged": make_result("nged")})
    queue = json.loads(summary.review_queue_path.read_text(encoding="utf-8"))

    assert queue
    assert {item["source_dataset_id"] for item in queue} == {"public-dataset"}
    assert {item["reason"] for item in queue} <= {"unknown", "conflict", "missing_evidence"}
    assert all(item["portal_id"] == "nged" for item in queue)
    assert all("synthetic-secret" not in json.dumps(item) for item in queue)


def test_failed_portal_retains_only_valid_queue_items_and_derives_missing_id(tmp_path: Path):
    queue_path = tmp_path / "cache" / "review-queue.json"
    queue_path.parent.mkdir(parents=True)
    queue_path.write_text(
        json.dumps(
            [
                {
                    "portal_id": "nged",
                    "source_dataset_id": "public-dataset",
                    "dimension": "access",
                    "reason": "missing_evidence",
                    "evidence_ids": [],
                },
                {"portal_id": "nged", "dimension": "access"},
                "not-a-queue-item",
            ]
        ),
        encoding="utf-8",
    )

    first = run_sync(tmp_path, {"nged": RuntimeError("offline")})
    first_bytes = first.review_queue_path.read_bytes()
    second = run_sync(tmp_path, {"nged": RuntimeError("still offline")})
    queue = json.loads(second.review_queue_path.read_text(encoding="utf-8"))

    assert len(queue) == 1
    assert queue[0]["source_dataset_id"] == "public-dataset"
    assert isinstance(queue[0]["id"], str)
    assert second.review_queue_path.read_bytes() == first_bytes


def test_persistence_failure_rolls_back_registry_without_publishing_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    initial = run_sync(tmp_path, {"nged": make_result("nged", title="Last valid title")})
    original_snapshot = initial.portals["nged"].snapshot_path
    original_snapshot_bytes = original_snapshot.read_bytes()
    original_queue_bytes = initial.review_queue_path.read_bytes()
    persist = catalogue_sync.persist_catalogue_result

    def fail_after_persist(*args, **kwargs):
        persist(*args, **kwargs)
        raise sqlite3.OperationalError("synthetic persistence failure")

    monkeypatch.setattr(catalogue_sync, "persist_catalogue_result", fail_after_persist)
    later = NOW + timedelta(minutes=5)
    summary = sync_catalogues(
        ["nged"],
        lambda portal: FakeClient("nged", {"nged": make_result("nged", title="Uncommitted title")}),
        tmp_path / "catalogue.sqlite3",
        tmp_path / "snapshots",
        later,
        fetcher=fake_fetch,
        review_queue_path=tmp_path / "cache" / "review-queue.json",
        policy_path=Path(__file__).parents[2] / "data" / "catalogue" / "maintenance-policy.json",
    )

    assert summary.status == "failed"
    with get_connection(tmp_path / "catalogue.sqlite3") as conn:
        row = conn.execute(
            "SELECT title, last_observation_id FROM catalogue_datasets WHERE portal_id = 'nged'"
        ).fetchone()
        observation_count = conn.execute(
            "SELECT COUNT(*) FROM catalogue_observations WHERE portal_id = 'nged'"
        ).fetchone()[0]
    assert row["title"] == "Last valid title"
    assert observation_count == 1
    assert original_snapshot.read_bytes() == original_snapshot_bytes
    assert initial.review_queue_path.read_bytes() == original_queue_bytes
    assert list((tmp_path / "snapshots").rglob("nged.json")) == [original_snapshot]


def test_cli_parser_rejects_unknown_portal_and_has_only_read_only_commands():
    from app.catalogue_cli import build_parser

    parser = build_parser()
    assert set(parser._subparsers._group_actions[0].choices) == {"sync", "diff", "review-queue"}
    with pytest.raises(SystemExit) as error:
        parser.parse_args(["sync", "--portal", "not-approved"])
    assert error.value.code == 1


def test_cli_missing_subcommand_exits_one():
    from app.catalogue_cli import main

    with pytest.raises(SystemExit) as error:
        main([])

    assert error.value.code == 1


@pytest.mark.parametrize("failure", ["missing", "malformed"])
def test_cli_invalid_diff_inputs_exit_one_safely(tmp_path: Path, failure: str, capsys: pytest.CaptureFixture[str]):
    from app.catalogue_cli import main

    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    after.write_text("{}", encoding="utf-8")
    if failure == "malformed":
        before.write_text("{not-json", encoding="utf-8")

    assert main(["diff", "--before", str(before), "--after", str(after)]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "failed"


def test_s3_queue_retention_preserves_unrequested_portal_items(tmp_path: Path):
    """S3: On subset sync, preserve existing queue items for unrequested portals."""
    queue_path = tmp_path / "cache" / "review-queue.json"
    # First sync with two portals
    first = run_sync(tmp_path, {"nged": make_result("nged"), "spen": make_result("spen")})
    first_queue = json.loads(first.review_queue_path.read_text(encoding="utf-8"))
    first_portals = {item["portal_id"] for item in first_queue}
    assert "nged" in first_portals or "spen" in first_portals

    # Second sync with only nged - spen items should be preserved
    second = sync_catalogues(
        ["nged"],
        lambda portal: FakeClient(
            next(pid for pid, reg in CATALOGUE_PORTALS.items() if reg is portal),
            {"nged": make_result("nged")},
        ),
        tmp_path / "catalogue.sqlite3",
        tmp_path / "snapshots",
        NOW + timedelta(minutes=5),
        fetcher=fake_fetch,
        review_queue_path=queue_path,
        policy_path=Path(__file__).parents[2] / "data" / "catalogue" / "maintenance-policy.json",
    )
    second_queue = json.loads(second.review_queue_path.read_text(encoding="utf-8"))
    second_portals = {item["portal_id"] for item in second_queue}
    # spen items should be preserved since spen was not requested
    assert "spen" in second_portals


def test_s3_partial_requested_portal_replaces_its_previous_queue_items(tmp_path: Path):
    """S3: A fresh partial classification pass replaces that portal's old queue."""
    queue_path = tmp_path / "cache" / "review-queue.json"
    run_sync(tmp_path, {"nged": make_result("nged", source_id="old-source")})

    partial = make_result("nged", source_id="new-source", complete=False)
    sync_catalogues(
        ["nged"],
        lambda portal: FakeClient("nged", {"nged": partial}),
        tmp_path / "catalogue.sqlite3",
        tmp_path / "snapshots",
        NOW + timedelta(minutes=5),
        fetcher=fake_fetch,
        review_queue_path=queue_path,
        policy_path=Path(__file__).parents[2]
        / "data"
        / "catalogue"
        / "maintenance-policy.json",
    )

    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    assert {item["source_dataset_id"] for item in queue} == {"new-source"}


def test_q3_snapshot_does_not_mutate_fetched_adapter_objects(tmp_path: Path):
    """Q3: Snapshot creation does not mutate the original fetched adapter objects."""
    result = make_result("nged")
    result.datasets[0].classification_evidence.append(
        ClassificationEvidence(
            id="nged:public-dataset:lifecycle",
            portal_id="nged",
            source_dataset_id="public-dataset",
            classification="lifecycle_status",
            source_value="active",
            evidence="The public source explicitly marks this dataset active.",
            confidence=EvidenceConfidence.high,
            observed_at=NOW,
        )
    )
    original_datasets = [d.model_dump(mode="json") for d in result.datasets]
    original_resources = [r.model_dump(mode="json") for r in result.resources]

    summary = run_sync(tmp_path, {"nged": result})

    # The original result objects should not have been mutated
    assert [d.model_dump(mode="json") for d in result.datasets] == original_datasets
    assert [r.model_dump(mode="json") for r in result.resources] == original_resources
    snapshot = json.loads(
        summary.portals["nged"].snapshot_path.read_text(encoding="utf-8")
    )
    assert snapshot["datasets"][0]["lifecycle_status"] == "unknown"

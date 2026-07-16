"""Behavioural tests for safe catalogue sync orchestration and CLI helpers."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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


def write_snapshot(path: Path, *datasets: CatalogueDataset) -> Path:
    path.write_text(
        json.dumps(
            {
                "manifest": {"portal_id": datasets[0].portal_id if datasets else "nged"},
                "datasets": [item.model_dump(mode="json") for item in datasets],
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
        ("resources_replaced", "public-dataset"),
        ("access_changed", "public-dataset"),
    }
    assert diff_snapshots(after, after).changes == ()


def test_review_queue_contains_only_stable_evidence_led_unresolved_cases(tmp_path: Path):
    summary = run_sync(tmp_path, {"nged": make_result("nged")})
    queue = json.loads(summary.review_queue_path.read_text(encoding="utf-8"))

    assert queue
    assert {item["source_dataset_id"] for item in queue} == {"public-dataset"}
    assert {item["reason"] for item in queue} <= {"unknown", "conflict", "missing_evidence"}
    assert all(item["portal_id"] == "nged" for item in queue)
    assert all("synthetic-secret" not in json.dumps(item) for item in queue)


def test_cli_parser_rejects_unknown_portal_and_has_only_read_only_commands():
    from app.catalogue_cli import build_parser

    parser = build_parser()
    assert set(parser._subparsers._group_actions[0].choices) == {"sync", "diff", "review-queue"}
    with pytest.raises(SystemExit) as error:
        parser.parse_args(["sync", "--portal", "not-approved"])
    assert error.value.code == 1

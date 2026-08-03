"""Public API contracts for immutable outage evidence."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import app.db as app_db
import pytest
from app.config import config
from app.outage_store import commit_ingestion_run
from app.outages import (
    OutageEvent,
    OutageFetchAttemptPublicV1,
    SourceSnapshot,
    source_snapshot_id,
)
from app.ssen_nafirs import SEPD_RESOURCE_ID, SHEPD_RESOURCE_ID
from fastapi.testclient import TestClient

MIGRATION_MESSAGE = "Outage API moved to /api/v1/outages."
DATASET_ID = "nafirs-hv-faults"
PACKAGE_ID = "nafirs-hv-faults"
ALLOWED_ORIGIN = "http://localhost:3000"
OUTAGE_REDIRECT_ALIASES = [
    ("/api/v1/outages/events/", "/api/v1/outages/events"),
    ("/api/v1/outages/summary/", "/api/v1/outages/summary"),
    (
        "/api/v1/outages/events/event-1/",
        "/api/v1/outages/events/event-1",
    ),
    ("/api/v1/outages/snapshots/", "/api/v1/outages/snapshots"),
    ("/api/v1/outages/events//", "/api/v1/outages/events"),
]


def _snapshot(
    *, resource_id: str, licence_area: str, digest: str, row_count: int
) -> SourceSnapshot:
    fetched_at = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    return SourceSnapshot(
        snapshot_id=source_snapshot_id(resource_id, digest),
        source_dataset_id=DATASET_ID,
        package_id=PACKAGE_ID,
        source_resource_id=resource_id,
        licence_area=licence_area,
        stable_source_url=f"https://data-api.ssen.co.uk/dataset/{resource_id}",
        source_modified_at=None,
        fetched_at=fetched_at,
        content_sha256=digest,
        byte_size=100,
        row_count=row_count,
        observed_columns=["incident", "customers"],
        licence_id="cc-by",
        licence_title="Creative Commons Attribution 4.0",
        licence_url="https://creativecommons.org/licenses/by/4.0/",
        attribution="SSEN Distribution",
        parser_version="ssen-nafirs-hv-v1",
        local_snapshot_path=f"blobs/{digest[:2]}/{digest}.csv",
    )


def _event(
    *,
    event_id: str,
    snapshot: SourceSnapshot,
    incident: str,
    district: str,
    year: int,
    cause_code: str | None,
    customers: int | None,
    minutes: int | None,
) -> OutageEvent:
    return OutageEvent(
        event_id=event_id,
        source_dataset_id=DATASET_ID,
        source_resource_id=snapshot.source_resource_id,
        source_snapshot_id=snapshot.snapshot_id,
        operator="SSEN Distribution",
        licence_area=snapshot.licence_area,
        incident_started_local=incident,
        timezone_name=None,
        reporting_year=year,
        voltage_kv=11.0,
        district_short_code=district,
        district_hv_reference=f"{district}-HV",
        network_reference=f"{district}-NETWORK",
        primary_nrn=None,
        primary_name=None,
        customers_affected=customers,
        customer_minutes_lost=minutes,
        average_minutes_off_supply=None,
        equipment_code=None,
        equipment=None,
        component_code=None,
        component=None,
        cause_code=cause_code,
        cause=None,
        contributory_cause_code=None,
        contributory_cause=None,
        damage=None,
        exceptional_event=None,
        quality_flags=[],
        raw_record={"incident": event_id, "customers": customers},
    )


def _commit(
    db_path: Path,
    *,
    run_id: str,
    snapshots: list[SourceSnapshot],
    events: list[OutageEvent],
) -> None:
    attempted_at = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    attempts = [
        OutageFetchAttemptPublicV1(
            attempt_id=f"attempt:{run_id}:{snapshot.source_resource_id}",
            run_id=run_id,
            source_resource_id=snapshot.source_resource_id,
            attempted_at=attempted_at,
            status="completed",
            response_status=200,
            source_modified_at=None,
            source_snapshot_id=snapshot.snapshot_id,
            content_sha256=snapshot.content_sha256,
            byte_size=snapshot.byte_size,
            error_code=None,
        )
        for snapshot in snapshots
    ]
    commit_ingestion_run(
        run_id=run_id,
        resources_seen=2,
        snapshots=snapshots,
        events=events,
        rejects=[],
        warnings=[],
        fetch_attempts=attempts,
        db_path=db_path,
    )


def _seed_database(db_path: Path) -> dict[str, Any]:
    old_sepd = _snapshot(
        resource_id=SEPD_RESOURCE_ID,
        licence_area="SEPD",
        digest="a" * 64,
        row_count=2,
    )
    old_shepd = _snapshot(
        resource_id=SHEPD_RESOURCE_ID,
        licence_area="SHEPD",
        digest="b" * 64,
        row_count=1,
    )
    removed = _event(
        event_id="removed-event",
        snapshot=old_sepd,
        incident="2024-01-01 01:00:00",
        district="OLD",
        year=2024,
        cause_code="10",
        customers=5,
        minutes=50,
    )
    old_kept = _event(
        event_id="old-kept",
        snapshot=old_sepd,
        incident="2024-01-02 01:00:00",
        district="OLD",
        year=2024,
        cause_code="11",
        customers=10,
        minutes=None,
    )
    old_north = _event(
        event_id="old-north",
        snapshot=old_shepd,
        incident="2024-01-03 01:00:00",
        district="NORTH",
        year=2024,
        cause_code=None,
        customers=None,
        minutes=None,
    )
    _commit(
        db_path,
        run_id="run-old",
        snapshots=[old_sepd, old_shepd],
        events=[removed, old_kept, old_north],
    )

    current_sepd = _snapshot(
        resource_id=SEPD_RESOURCE_ID,
        licence_area="SEPD",
        digest="c" * 64,
        row_count=2,
    )
    current_shepd = _snapshot(
        resource_id=SHEPD_RESOURCE_ID,
        licence_area="SHEPD",
        digest="d" * 64,
        row_count=1,
    )
    event_one = _event(
        event_id="event-1",
        snapshot=current_sepd,
        incident="2026-01-01 01:00:00",
        district="SWIN",
        year=2026,
        cause_code="99",
        customers=20,
        minutes=200,
    )
    event_two = _event(
        event_id="event-2",
        snapshot=current_sepd,
        incident="2026-02-01 01:00:00",
        district="READ",
        year=2026,
        cause_code="98",
        customers=None,
        minutes=None,
    )
    event_three = _event(
        event_id="event-3",
        snapshot=current_shepd,
        incident="2025-03-01 01:00:00",
        district="NORTH",
        year=2025,
        cause_code="99",
        customers=30,
        minutes=300,
    )
    _commit(
        db_path,
        run_id="run-current",
        snapshots=[current_sepd, current_shepd],
        events=[event_one, event_two, event_three],
    )
    return {
        "old_ids": [
            snapshot.snapshot_id
            for snapshot in sorted(
                (old_sepd, old_shepd),
                key=lambda item: item.source_resource_id,
            )
        ],
        "current_ids": [
            snapshot.snapshot_id
            for snapshot in sorted(
                (current_sepd, current_shepd),
                key=lambda item: item.source_resource_id,
            )
        ],
        "event": event_one,
    }


@pytest.fixture
def seeded_db(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    db_path = tmp_path / "outages.sqlite3"
    return db_path, _seed_database(db_path)


@pytest.fixture
def client(
    tmp_path: Path,
    seeded_db: tuple[Path, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    outage_db, _ = seeded_db
    app_db_path = tmp_path / "app.sqlite3"
    permitted = {outage_db.resolve(), app_db_path.resolve()}
    opened: list[Path] = []
    real_connect = sqlite3.connect

    def guarded_connect(
        database: str | Path, *args: object, **kwargs: object
    ) -> sqlite3.Connection:
        resolved = Path(database).resolve()
        if resolved not in permitted:
            raise AssertionError(f"application opened unexpected DB: {resolved}")
        opened.append(resolved)
        return real_connect(str(resolved), *args, **kwargs)

    old_app_db = config.db_path
    old_outage_db = config.outage_db_path
    object.__setattr__(config, "db_path", app_db_path)
    object.__setattr__(config, "outage_db_path", outage_db)
    monkeypatch.setattr(app_db.sqlite3, "connect", guarded_connect)
    try:
        from app.main import app

        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        object.__setattr__(config, "db_path", old_app_db)
        object.__setattr__(config, "outage_db_path", old_outage_db)
    assert outage_db.resolve() in opened
    assert app_db_path.resolve() not in opened
    assert set(opened) <= permitted


@pytest.fixture
def empty_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    outage_db = tmp_path / "empty-outages.sqlite3"
    app_db_path = tmp_path / "empty-app.sqlite3"
    old_app_db = config.db_path
    old_outage_db = config.outage_db_path
    object.__setattr__(config, "db_path", app_db_path)
    object.__setattr__(config, "outage_db_path", outage_db)
    try:
        from app.main import app

        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        object.__setattr__(config, "db_path", old_app_db)
        object.__setattr__(config, "outage_db_path", old_outage_db)


def test_outage_list_uses_seeded_temporary_database(
    client: TestClient, seeded_db: tuple[Path, dict[str, Any]]
) -> None:
    response = client.get("/api/v1/outages/events?licence_area=SEPD&limit=1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert len(payload["items"]) == 1
    assert payload["items"][0]["licence_area"] == "SEPD"
    assert payload["evidence_scope"] == {
        "snapshot_ids": seeded_db[1]["current_ids"],
        "source_resource_ids": sorted([SEPD_RESOURCE_ID, SHEPD_RESOURCE_ID]),
        "resolution": "current_atomic_set",
    }


def test_health_reports_static_sync_capability_without_local_evidence(
    empty_client: TestClient,
) -> None:
    health = empty_client.get("/api/health")
    events = empty_client.get("/api/v1/outages/events")

    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "data_status": "verified_analytical_source_available_for_local_sync",
    }
    assert events.status_code == 503


def test_health_never_denies_queryable_verified_outage_evidence(
    client: TestClient,
) -> None:
    health = client.get("/api/health")
    events = client.get("/api/v1/outages/events")

    assert health.status_code == 200
    assert health.json()["data_status"] == (
        "verified_analytical_source_available_for_local_sync"
    )
    assert health.json()["data_status"] != "no_verified_analytical_data"
    assert events.status_code == 200
    assert events.json()["total"] == 3


def test_outage_detail_exposes_exact_safe_provenance(
    client: TestClient, seeded_db: tuple[Path, dict[str, Any]]
) -> None:
    event = seeded_db[1]["event"]
    response = client.get(
        f"/api/v1/outages/events/{event.event_id}",
        params={"source_snapshot_id": event.source_snapshot_id},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["raw_record"] == event.raw_record
    assert payload["source_snapshot_id"] == event.source_snapshot_id


def test_outage_detail_requires_exactly_one_snapshot(client: TestClient) -> None:
    assert client.get("/api/v1/outages/events/event-1").status_code == 422
    assert client.get(
        "/api/v1/outages/events/event-1",
        params=[("source_snapshot_id", "one"), ("source_snapshot_id", "two")],
    ).status_code == 422


def test_unknown_outage_detail_is_404(
    client: TestClient, seeded_db: tuple[Path, dict[str, Any]]
) -> None:
    snapshot_id = seeded_db[1]["current_ids"][0]
    response = client.get(
        "/api/v1/outages/events/unknown",
        params={"source_snapshot_id": snapshot_id},
    )
    assert response.status_code == 404
    assert "unknown" not in response.text


def test_summary_supports_accepted_filters_and_unknown_totals(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/v1/outages/summary",
        params={
            "licence_area": "SEPD",
            "reporting_year": 2026,
        },
    )
    assert response.status_code == 200
    assert response.json()["summary"] == {
        "event_count": 2,
        "customers_affected_total": 20,
        "customer_minutes_lost_total": 200,
        "incident_started_local_min": "2026-01-01 01:00:00",
        "incident_started_local_max": "2026-02-01 01:00:00",
    }
    empty = client.get(
        "/api/v1/outages/summary", params={"reporting_year": 1900}
    ).json()["summary"]
    assert empty == {
        "event_count": 0,
        "customers_affected_total": None,
        "customer_minutes_lost_total": None,
        "incident_started_local_min": None,
        "incident_started_local_max": None,
    }


def test_event_items_and_count_apply_identical_filters(client: TestClient) -> None:
    payload = client.get(
        "/api/v1/outages/events",
        params={
            "licence_area": "SEPD",
            "district_short_code": "SWIN",
            "reporting_year": 2026,
            "cause_code": "99",
        },
    ).json()
    assert payload["total"] == 1
    assert [item["event_id"] for item in payload["items"]] == ["event-1"]


def test_zero_result_filters_keep_resolved_scope(
    client: TestClient, seeded_db: tuple[Path, dict[str, Any]]
) -> None:
    payload = client.get(
        "/api/v1/outages/events", params={"district_short_code": "MISSING"}
    ).json()
    assert payload["items"] == []
    assert payload["total"] == 0
    assert set(payload["evidence_scope"]["snapshot_ids"]) == set(
        seeded_db[1]["current_ids"]
    )


def test_old_snapshots_replay_and_removed_event_is_not_current(
    client: TestClient, seeded_db: tuple[Path, dict[str, Any]]
) -> None:
    current = client.get("/api/v1/outages/events", params={"limit": 100}).json()
    assert "removed-event" not in {item["event_id"] for item in current["items"]}
    old = client.get(
        "/api/v1/outages/events",
        params=[
            *(('source_snapshot_id', item) for item in seeded_db[1]["old_ids"]),
            ("limit", "100"),
        ],
    )
    assert old.status_code == 200
    assert old.json()["evidence_scope"]["resolution"] == "explicit_snapshot_set"
    assert "removed-event" in {item["event_id"] for item in old.json()["items"]}


def test_snapshot_list_is_public_projection(client: TestClient) -> None:
    response = client.get("/api/v1/outages/snapshots")
    assert response.status_code == 200
    assert len(response.json()) == 4
    text = response.text
    assert "local_snapshot_path" not in text
    assert "signed_redirect" not in text
    assert "blobs/" not in text


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/v1/outages/events", {"reporting_year": 1899}),
        ("/api/v1/outages/events", {"reporting_year": 2101}),
        ("/api/v1/outages/summary", {"reporting_year": 1899}),
        ("/api/v1/outages/summary", {"reporting_year": 2101}),
        ("/api/v1/outages/events", {"limit": 0}),
        ("/api/v1/outages/events", {"limit": 1001}),
        ("/api/v1/outages/events", {"offset": -1}),
        ("/api/v1/outages/snapshots", {"limit": 0}),
        ("/api/v1/outages/snapshots", {"offset": -1}),
    ],
)
def test_outage_api_rejects_invalid_bounds(
    client: TestClient, path: str, params: dict[str, int]
) -> None:
    response = client.get(path, params=params)
    assert response.status_code == 422
    assert "between" not in response.text


def test_invalid_explicit_snapshot_is_safe_422(client: TestClient) -> None:
    response = client.get(
        "/api/v1/outages/events",
        params={"source_snapshot_id": "private-path-C:/Users/name/database.sqlite3"},
    )
    assert response.status_code == 422
    assert "C:/Users" not in response.text


def test_empty_current_set_is_fixed_safe_503(empty_client: TestClient) -> None:
    responses = [
        empty_client.get("/api/v1/outages/events"),
        empty_client.get("/api/v1/outages/summary"),
    ]
    assert [response.status_code for response in responses] == [503, 503]
    assert responses[0].json() == responses[1].json()
    assert "sqlite" not in responses[0].text.lower()


@pytest.mark.parametrize(
    "method", ["head", "options", "post", "put", "patch", "delete"]
)
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/outages/events",
        "/api/v1/outages/summary",
        "/api/v1/outages/events/event-1",
        "/api/v1/outages/snapshots",
    ],
)
def test_outage_routes_are_read_only(
    client: TestClient, method: str, path: str
) -> None:
    assert getattr(client, method)(path).status_code == 405


def test_outage_openapi_contains_no_write_method(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        "/api/v1/outages/events",
        "/api/v1/outages/summary",
        "/api/v1/outages/events/{event_id}",
        "/api/v1/outages/snapshots",
    ):
        assert set(paths[path]) == {"get"}


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize(("alias", "canonical"), OUTAGE_REDIRECT_ALIASES)
def test_outage_trailing_slash_aliases_redirect_to_accepted_routes(
    client: TestClient,
    alias: str,
    canonical: str,
    method: str,
) -> None:
    response = getattr(client, method)(alias, follow_redirects=False)
    assert response.status_code == 307
    assert urlsplit(response.headers["location"]).path == canonical


@pytest.mark.parametrize(("alias", "_canonical"), OUTAGE_REDIRECT_ALIASES)
def test_outage_redirect_alias_preflight_preserves_fixed_405(
    client: TestClient,
    alias: str,
    _canonical: str,
) -> None:
    response = client.options(
        alias,
        follow_redirects=False,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 405
    assert response.json() == {"detail": "Request failed", "code": "http_error"}
    assert "access-control-allow-methods" not in response.headers
    assert "POST" not in response.headers.get("access-control-allow-methods", "")


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/outages/events//event-1",
        "/api/v1/outages/events/event%2F1",
        "/api/v1/outages/unrelated/",
    ],
)
def test_non_route_slash_paths_are_not_captured_as_outage_aliases(
    client: TestClient,
    path: str,
) -> None:
    actual = client.get(path, follow_redirects=False)
    assert actual.status_code == 404

    preflight = client.options(
        path,
        follow_redirects=False,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
    )
    assert preflight.status_code == 200
    assert "POST" in preflight.headers["access-control-allow-methods"]


@pytest.mark.parametrize("requested_method", ["GET", "POST", "DELETE"])
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/outages/events",
        "/api/v1/outages/summary",
        "/api/v1/outages/events/event-1",
        "/api/v1/outages/snapshots",
    ],
)
def test_versioned_outage_preflight_preserves_fixed_405(
    client: TestClient,
    path: str,
    requested_method: str,
) -> None:
    response = client.options(
        path,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": requested_method,
        },
    )
    assert response.status_code == 405
    assert response.json() == {"detail": "Request failed", "code": "http_error"}
    assert "access-control-allow-methods" not in response.headers


@pytest.mark.parametrize("requested_method", ["GET", "POST", "DELETE"])
@pytest.mark.parametrize(
    "path", ["/api/outages", "/api/outage-snapshots"]
)
def test_legacy_outage_preflight_preserves_fixed_410(
    client: TestClient,
    path: str,
    requested_method: str,
) -> None:
    response = client.options(
        path,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": requested_method,
        },
    )
    assert response.status_code == 410
    assert response.json() == {"detail": MIGRATION_MESSAGE}
    assert "access-control-allow-methods" not in response.headers


@pytest.mark.parametrize(
    ("path", "requested_method"),
    [("/api/health", "GET"), ("/api/demo/analyse", "POST")],
)
def test_non_outage_preflight_keeps_global_cors_behavior(
    client: TestClient,
    path: str,
    requested_method: str,
) -> None:
    response = client.options(
        path,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": requested_method,
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert requested_method in response.headers["access-control-allow-methods"]


def test_root_info_lists_the_versioned_outage_get_surface(client: TestClient) -> None:
    endpoints = client.get("/").json()["endpoints"]
    for path in (
        "/api/v1/outages/events",
        "/api/v1/outages/summary",
        "/api/v1/outages/events/{event_id}",
        "/api/v1/outages/snapshots",
    ):
        assert path in endpoints
    assert not any(path.startswith("/api/outages") for path in endpoints)
    assert "/api/outage-snapshots" not in endpoints


@pytest.mark.parametrize(
    "path",
    [
        "/api/outages",
        "/api/outages/events",
        "/api/outages/summary?reporting_year=2026",
        "/api/outage-snapshots",
    ],
)
def test_unversioned_aliases_have_one_stable_migration_response(
    client: TestClient, path: str
) -> None:
    response = client.get(path)
    assert response.status_code == 410
    assert response.json() == {"detail": MIGRATION_MESSAGE}

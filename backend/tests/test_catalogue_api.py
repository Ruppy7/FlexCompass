"""Public contracts for the versioned read-only catalogue API."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from app.catalogue_adapters import CatalogueFetchResult
from app.catalogue_api_models import sanitise_public_url
from app.catalogue_identity import decode_dataset_ref, encode_dataset_ref
from app.catalogue_models import (
    CATALOGUE_PORTAL_IDS,
    CatalogueDataset,
    ClassificationEvidence,
    DatasetResource,
)
from app.catalogue_routes import router as catalogue_router
from app.catalogue_store import (
    catalogue_assessment_key,
    persist_catalogue_assessment,
    persist_catalogue_result,
    record_catalogue_refresh_attempt,
)
from app.catalogue_sync import _canonical_json, _snapshot_identity
from app.config import config
from app.db import get_connection, run_migrations
from app.main import create_app
from fastapi.testclient import TestClient

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
FORBIDDEN_KEYS = {
    "raw_record",
    "raw_pages",
    "snapshot_path",
    "request_url",
    "endpoint",
    "safe_error",
    "auth_env_var",
    "reviewer",
    "reviewer_identity",
    "credentials",
}


def _assert_public(value: object) -> None:
    if isinstance(value, dict):
        assert FORBIDDEN_KEYS.isdisjoint(value)
        for key, item in value.items():
            if key.endswith("url") and isinstance(item, str):
                parsed = urlsplit(item)
                assert parsed.query == ""
                assert parsed.fragment == ""
            _assert_public(item)
    elif isinstance(value, list):
        for item in value:
            _assert_public(item)


def _dataset(
    source_id: str,
    title: str,
    *,
    lifecycle: str = "active",
    observed_at: datetime = NOW,
) -> CatalogueDataset:
    resource = DatasetResource(
        id=f"resource:{source_id}",
        portal_id="nged",
        source_dataset_id=source_id,
        name=f"Resource {source_id}",
        url=f"https://example.invalid/{source_id}.csv?token=secret#private",
        observed_at=observed_at,
        raw_record={"credentials": "secret"},
    )
    evidence = ClassificationEvidence(
        id=f"evidence:{source_id}",
        portal_id="nged",
        source_dataset_id=source_id,
        classification="access_status",
        evidence="Anonymous metadata was visible.",
        source_value={"request_url": "https://private.invalid/?token=x"},
        source_url="https://example.invalid/evidence?token=secret#private",
        observed_at=observed_at,
        raw_record={"reviewer_identity": "private"},
    )
    return CatalogueDataset(
        id=f"nged:{source_id}",
        portal_id="nged",
        source_dataset_id=source_id,
        title=title,
        description=f"Description for {title}",
        catalogue_page_url=(
            f"https://example.invalid/datasets/{source_id}?token=secret#private"
        ),
        metadata_api_url="https://example.invalid/api?id=private#fragment",
        portal_url="https://example.invalid/?private=yes",
        api_url="https://example.invalid/api#private",
        observed_at=observed_at,
        lifecycle_status=lifecycle,
        publication_pattern="periodic",
        access_status="public",
        resources=[resource],
        classification_evidence=[evidence],
        raw_record={"raw_pages": ["private"]},
    )


def _seed_complete_catalogue(
    db_path: Path,
    snapshot_root: Path,
    *,
    observed_at: datetime = NOW,
    snapshot_name: str = "complete.json",
    datasets: tuple[CatalogueDataset, ...] | None = None,
) -> tuple[str, Path]:
    datasets = datasets or (
        _dataset("z-last", "Zeta dataset", lifecycle="retired", observed_at=observed_at),
        _dataset("folder/dataset:id", "Alpha flexibility dataset", observed_at=observed_at),
        _dataset("middle", "Middle dataset", observed_at=observed_at),
    )
    resources = tuple(item for dataset in datasets for item in dataset.resources)
    raw_pages = ({"request_url": "https://private.invalid/?token=x"},)
    core = {
        "datasets": [item.model_dump(mode="json") for item in datasets],
        "resources": [item.model_dump(mode="json") for item in resources],
        "raw_pages": list(raw_pages),
    }
    content_hash = hashlib.sha256(
        _canonical_json(_snapshot_identity(core))
    ).hexdigest()
    snapshot = snapshot_root / "nged" / snapshot_name
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(
        json.dumps(
            {
                "manifest": {
                    "adapter_version": "1",
                    "schema_version": 1,
                    "portal_id": "nged",
                    "portal_status": "complete",
                    "observed_at": observed_at.isoformat(),
                    "dataset_count": len(datasets),
                    "resource_count": len(resources),
                    "expected_count": len(datasets),
                    "complete": True,
                    "content_hash": content_hash,
                    "snapshot_path": snapshot.as_posix(),
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
        expected_count=len(datasets),
        complete=True,
        warnings=[],
        raw_pages=list(raw_pages),
    )
    with get_connection(db_path) as connection:
        persisted = persist_catalogue_result(
            connection,
            result,
            snapshot.as_posix(),
            content_hash,
            status="complete",
        )
        record_catalogue_refresh_attempt(
            connection,
            portal_id="nged",
            attempted_at=observed_at,
            status="complete",
            observation_id=persisted.observation_id,
            warnings=[],
            safe_error_text=None,
        )
        persist_catalogue_assessment(
            connection,
            assessment_id=catalogue_assessment_key(
                "nged", "middle", persisted.observation_id, "maintenance"
            ),
            portal_id="nged",
            source_dataset_id="middle",
            observation_id=persisted.observation_id,
            assessment_type="maintenance",
            assessment_value="stale",
            confidence="high",
            rationale=["reviewer-private-sentinel"],
            missing_evidence=["credentials-private-sentinel"],
            assessed_at=observed_at,
        )
        persist_catalogue_assessment(
            connection,
            assessment_id=catalogue_assessment_key(
                "nged", "z-last", persisted.observation_id, "lifecycle"
            ),
            portal_id="nged",
            source_dataset_id="z-last",
            observation_id=persisted.observation_id,
            assessment_type="lifecycle",
            assessment_value="stale",
            confidence="high",
            rationale=["This non-maintenance value must not drive maintenance."],
            missing_evidence=[],
            assessed_at=observed_at,
        )
    return persisted.observation_id, snapshot


def _seed_partial_observation(
    db_path: Path,
    snapshot_root: Path,
    *,
    observed_at: datetime,
) -> str:
    partial = CatalogueFetchResult(
        portal_id="nged",
        observed_at=observed_at,
        datasets=[],
        resources=[],
        expected_count=1,
        complete=False,
        warnings=["Incomplete public pagination evidence."],
        raw_pages=[],
    )
    with get_connection(db_path) as connection:
        persisted = persist_catalogue_result(
            connection,
            partial,
            (snapshot_root / "partial.json").as_posix(),
            hashlib.sha256(observed_at.isoformat().encode()).hexdigest(),
            status="partial",
        )
        record_catalogue_refresh_attempt(
            connection,
            portal_id="nged",
            attempted_at=observed_at,
            status="partial",
            observation_id=persisted.observation_id,
            warnings=partial.warnings,
            safe_error_text=None,
        )
    return persisted.observation_id


@pytest.fixture
def catalogue_client(tmp_path: Path) -> TestClient:
    settings = replace(
        config,
        db_path=tmp_path / "primary.sqlite3",
        outage_db_path=tmp_path / "outages.sqlite3",
        catalogue_db_path=tmp_path / "catalogue.sqlite3",
        catalogue_snapshot_dir=tmp_path / "snapshots",
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        _seed_complete_catalogue(
            settings.catalogue_db_path,
            settings.catalogue_snapshot_dir,
        )
        _seed_partial_observation(
            settings.catalogue_db_path,
            settings.catalogue_snapshot_dir,
            observed_at=NOW - timedelta(days=1),
        )
        yield client


def test_dataset_ref_round_trips_source_ids_with_slashes() -> None:
    ref = encode_dataset_ref("ssen", "folder/dataset:id")
    assert decode_dataset_ref(ref) == ("ssen", "folder/dataset:id")
    assert "=" not in ref
    assert "/" not in ref


def test_dataset_ref_encoder_enforces_decoder_length_boundary() -> None:
    with pytest.raises(ValueError):
        encode_dataset_ref("ssen", "x" * 2049)


@pytest.mark.parametrize(
    "value",
    [
        "http://user:pass@example.com/path",
        "http://127.0.0.1/path",
        "http://10.0.0.1/path",
        "http://169.254.1.1/path",
        "http://192.168.1.1/path",
        "http://[::1]/path",
        "http://2130706433/path",
        "http://localhost/path",
        "http://catalogue.local/path",
        "http://catalogue.internal/path",
        "http://example.com:bad/path",
        "http://example.com/line\nfeed",
        "http:\\localhost\\private",
    ],
)
def test_public_url_sanitiser_omits_credentials_and_local_or_malformed_urls(
    value: str,
) -> None:
    assert sanitise_public_url(value) is None


@pytest.mark.parametrize(
    "value",
    [
        "x" * 2049,
        "%2F",
        "not-base64",
        "W10=",
        "W10",
        "WyJ1bmtub3duIiwieCJd",
        "WyJzc2VuIiwiIl0",
        "WyJzc2VuIiwieCJd=",
    ],
)
def test_dataset_ref_rejects_malformed_or_noncanonical_input(value: str) -> None:
    with pytest.raises(ValueError):
        decode_dataset_ref(value)


def test_catalogue_router_is_get_only() -> None:
    for route in catalogue_router.routes:
        assert route.methods <= {"GET", "HEAD"}


def test_api_startup_migrates_distinct_catalogue_database(tmp_path: Path) -> None:
    app_db = tmp_path / "app.sqlite3"
    outage_db = tmp_path / "outage.sqlite3"
    catalogue_db = tmp_path / "catalogue" / "registry.sqlite3"
    settings = replace(
        config,
        db_path=app_db,
        outage_db_path=outage_db,
        catalogue_db_path=catalogue_db,
        catalogue_snapshot_dir=tmp_path / "snapshots",
    )
    run_migrations(catalogue_db)
    with sqlite3.connect(catalogue_db) as connection:
        connection.execute("DROP TABLE catalogue_refresh_attempts")
        connection.execute("DELETE FROM schema_version WHERE version = 8")
    with TestClient(create_app(settings)):
        pass
    with sqlite3.connect(catalogue_db) as connection:
        versions = connection.execute(
            "SELECT version FROM schema_version ORDER BY version"
        ).fetchall()
    assert versions[-1] == (8,)
    assert outage_db.exists()
    assert not app_db.exists()


def test_injected_apps_keep_seed_cors_and_databases_isolated(tmp_path: Path) -> None:
    first_settings = replace(
        config,
        db_path=tmp_path / "first-primary.sqlite3",
        outage_db_path=tmp_path / "first-outage.sqlite3",
        catalogue_db_path=tmp_path / "first-catalogue.sqlite3",
        catalogue_snapshot_dir=tmp_path / "first-snapshots",
        default_seed=11,
        cors_origins=("https://first.example",),
    )
    second_settings = replace(
        config,
        db_path=tmp_path / "second-primary.sqlite3",
        outage_db_path=tmp_path / "second-outage.sqlite3",
        catalogue_db_path=tmp_path / "second-catalogue.sqlite3",
        catalogue_snapshot_dir=tmp_path / "second-snapshots",
        default_seed=22,
        cors_origins=("https://second.example",),
    )
    with (
        TestClient(create_app(first_settings)) as first,
        TestClient(create_app(second_settings)) as second,
    ):
        assert first.get("/health").json()["seed"] == 11
        assert second.get("/health").json()["seed"] == 22
        first_cors = first.get(
            "/health", headers={"Origin": "https://first.example"}
        )
        second_cors = second.get(
            "/health", headers={"Origin": "https://second.example"}
        )
        assert first_cors.headers["access-control-allow-origin"] == (
            "https://first.example"
        )
        assert second_cors.headers["access-control-allow-origin"] == (
            "https://second.example"
        )
        assert "access-control-allow-origin" not in first.get(
            "/health", headers={"Origin": "https://second.example"}
        ).headers


def test_portals_expose_all_configured_public_identities_and_safe_state(
    catalogue_client: TestClient,
) -> None:
    response = catalogue_client.get("/api/v1/catalogue/portals")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 7
    assert {item["portal_id"] for item in payload["items"]} == set(
        CATALOGUE_PORTAL_IDS
    )
    nged = next(item for item in payload["items"] if item["portal_id"] == "nged")
    assert nged["current_attempt_status"] == "complete"
    assert nged["operational_review_window_hours"] == 168
    assert nged["last_valid_dataset_count"] == 3
    assert nged["snapshot_available"] is True
    _assert_public(payload)


def test_portal_detail_keeps_last_valid_evidence_after_failed_refresh(
    catalogue_client: TestClient,
) -> None:
    settings = catalogue_client.app.state.settings
    with get_connection(settings.catalogue_db_path) as connection:
        record_catalogue_refresh_attempt(
            connection,
            portal_id="nged",
            attempted_at=NOW + timedelta(hours=1),
            status="failed",
            observation_id=None,
            warnings=[],
            safe_error_text="private upstream detail",
        )
    response = catalogue_client.get("/api/v1/catalogue/portals/nged")
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_attempt_status"] == "failed"
    assert payload["last_valid_dataset_count"] == 3
    assert payload["snapshot_available"] is True
    assert "private upstream detail" not in response.text


def test_portal_detail_keeps_last_valid_evidence_after_partial_refresh(
    catalogue_client: TestClient,
) -> None:
    settings = catalogue_client.app.state.settings
    partial = CatalogueFetchResult(
        portal_id="nged",
        observed_at=NOW + timedelta(hours=1),
        datasets=[],
        resources=[],
        expected_count=1,
        complete=False,
        warnings=["Incomplete public pagination evidence."],
        raw_pages=[],
    )
    with get_connection(settings.catalogue_db_path) as connection:
        persisted = persist_catalogue_result(
            connection,
            partial,
            (settings.catalogue_snapshot_dir / "partial.json").as_posix(),
            "partial-hash",
            status="partial",
        )
        record_catalogue_refresh_attempt(
            connection,
            portal_id="nged",
            attempted_at=partial.observed_at,
            status="partial",
            observation_id=persisted.observation_id,
            warnings=partial.warnings,
            safe_error_text=None,
        )
    payload = catalogue_client.get("/api/v1/catalogue/portals/nged").json()
    assert payload["current_attempt_status"] == "partial"
    assert payload["last_valid_dataset_count"] == 3
    assert payload["snapshot_available"] is True


def test_corrupt_newest_complete_projects_degraded_older_fallback(
    catalogue_client: TestClient,
) -> None:
    settings = catalogue_client.app.state.settings
    newest_id, newest_path = _seed_complete_catalogue(
        settings.catalogue_db_path,
        settings.catalogue_snapshot_dir,
        observed_at=NOW + timedelta(hours=2),
        snapshot_name="newest.json",
        datasets=(
            _dataset(
                "newest-only",
                "Newest only",
                observed_at=NOW + timedelta(hours=2),
            ),
        ),
    )
    newest_path.write_text("corrupt", encoding="utf-8")
    portal = catalogue_client.get("/api/v1/catalogue/portals/nged").json()
    datasets = catalogue_client.get(
        "/api/v1/catalogue/datasets", params={"portal_id": "nged"}
    ).json()
    assert portal["last_complete_observation_id"] == newest_id
    assert portal["latest_complete_validation_state"] == "invalid"
    assert portal["degraded"] is True
    assert portal["last_valid_dataset_count"] == 3
    assert {item["source_dataset_id"] for item in datasets["items"]} == {
        "folder/dataset:id",
        "middle",
        "z-last",
    }


def test_dataset_listing_has_stable_pagination_and_filters(
    catalogue_client: TestClient,
) -> None:
    first = catalogue_client.get(
        "/api/v1/catalogue/datasets",
        params={"portal_id": "nged", "limit": 2, "offset": 0},
    ).json()
    second = catalogue_client.get(
        "/api/v1/catalogue/datasets",
        params={"portal_id": "nged", "limit": 2, "offset": 2},
    ).json()
    assert first["total"] == 3
    assert [item["source_dataset_id"] for item in first["items"]] == [
        "folder/dataset:id",
        "middle",
    ]
    assert [item["source_dataset_id"] for item in second["items"]] == ["z-last"]
    assert catalogue_client.get(
        "/api/v1/catalogue/datasets", params={"q": "flexibility"}
    ).json()["total"] == 1
    assert catalogue_client.get(
        "/api/v1/catalogue/datasets", params={"lifecycle_status": "retired"}
    ).json()["total"] == 1
    assert catalogue_client.get(
        "/api/v1/catalogue/datasets", params={"publication_pattern": "periodic"}
    ).json()["total"] == 3
    assert catalogue_client.get(
        "/api/v1/catalogue/datasets", params={"access_status": "public"}
    ).json()["total"] == 3
    maintenance = catalogue_client.get(
        "/api/v1/catalogue/datasets", params={"maintenance_state": "stale"}
    ).json()
    assert [item["source_dataset_id"] for item in maintenance["items"]] == [
        "middle"
    ]
    assert catalogue_client.get(
        "/api/v1/catalogue/datasets", params={"maintenance_state": "unknown"}
    ).json()["total"] == 0


def test_dataset_detail_children_and_observations_are_safe(
    catalogue_client: TestClient,
) -> None:
    dataset_ref = encode_dataset_ref("nged", "folder/dataset:id")
    paths = [
        f"/api/v1/catalogue/datasets/{dataset_ref}",
        f"/api/v1/catalogue/datasets/{dataset_ref}/resources",
        f"/api/v1/catalogue/datasets/{dataset_ref}/evidence",
        f"/api/v1/catalogue/datasets/{dataset_ref}/assessments",
        "/api/v1/catalogue/observations",
    ]
    for path in paths:
        response = catalogue_client.get(path)
        assert response.status_code == 200, path
        _assert_public(response.json())
    detail = catalogue_client.get(paths[0]).json()
    assert detail["dataset_ref"] == dataset_ref
    assert detail["source_dataset_id"] == "folder/dataset:id"
    resource_url = catalogue_client.get(paths[1]).json()["items"][0]["url"]
    assert resource_url == "https://example.invalid/folder/dataset:id.csv"
    maintenance_ref = encode_dataset_ref("nged", "middle")
    assessment_text = catalogue_client.get(
        f"/api/v1/catalogue/datasets/{maintenance_ref}/assessments"
    ).text
    assert "reviewer-private-sentinel" not in assessment_text
    assert "credentials-private-sentinel" not in assessment_text


def test_observations_are_stably_ordered_and_paginated(
    catalogue_client: TestClient,
) -> None:
    first = catalogue_client.get(
        "/api/v1/catalogue/observations", params={"limit": 1, "offset": 0}
    ).json()
    second = catalogue_client.get(
        "/api/v1/catalogue/observations", params={"limit": 1, "offset": 1}
    ).json()
    assert first["total"] == 2
    assert first["items"][0]["portal_id"] == "nged"
    assert first["items"][0]["status"] == "complete"
    assert second["items"][0]["status"] == "partial"
    assert first["items"][0]["observed_at"] > second["items"][0]["observed_at"]
    assert catalogue_client.get(
        "/api/v1/catalogue/observations",
        params={"portal_id": "nged", "status": "partial"},
    ).json()["total"] == 1


def test_no_valid_complete_is_unavailable_and_legacy_rows_are_never_read(
    tmp_path: Path,
) -> None:
    settings = replace(
        config,
        db_path=tmp_path / "primary.sqlite3",
        outage_db_path=tmp_path / "outage.sqlite3",
        catalogue_db_path=tmp_path / "catalogue.sqlite3",
        catalogue_snapshot_dir=tmp_path / "snapshots",
    )
    with TestClient(create_app(settings)) as client:
        with get_connection(settings.catalogue_db_path) as connection:
            connection.execute(
                """INSERT INTO portal_datasets (
                       id, name, portal_url, fields_json,
                       useful_for_json, limitations_json
                   ) VALUES (?, ?, ?, '[]', '[]', '[]')""",
                (
                    "legacy-private-sentinel",
                    "legacy-private-sentinel",
                    "http://user:pass@127.0.0.1/private",
                ),
            )
        _seed_partial_observation(
            settings.catalogue_db_path,
            settings.catalogue_snapshot_dir,
            observed_at=NOW,
        )
        portal = client.get("/api/v1/catalogue/portals/nged").json()
        datasets = client.get("/api/v1/catalogue/datasets").json()
        observations = client.get("/api/v1/catalogue/observations").json()
    assert portal["snapshot_available"] is False
    assert portal["latest_complete_validation_state"] == "unavailable"
    assert portal["last_valid_dataset_count"] == 0
    assert datasets["total"] == 0
    assert observations["total"] == 1
    assert observations["items"][0]["status"] == "partial"
    assert "legacy-private-sentinel" not in json.dumps(
        [portal, datasets, observations]
    )


@pytest.mark.parametrize("value", ["not-base64", "WyJzc2VuIiwieCJd="])
def test_malformed_dataset_reference_is_safe_422(
    catalogue_client: TestClient,
    value: str,
) -> None:
    response = catalogue_client.get(f"/api/v1/catalogue/datasets/{value}")
    assert response.status_code == 422
    assert "base64" not in response.text.lower()


def test_missing_dataset_and_unknown_portal_are_404(
    catalogue_client: TestClient,
) -> None:
    missing = encode_dataset_ref("nged", "missing")
    assert catalogue_client.get(
        f"/api/v1/catalogue/datasets/{missing}"
    ).status_code == 404
    assert catalogue_client.get(
        "/api/v1/catalogue/portals/not-a-portal"
    ).status_code == 404


@pytest.mark.parametrize("limit", [0, 201])
def test_catalogue_pagination_is_bounded(
    catalogue_client: TestClient,
    limit: int,
) -> None:
    assert catalogue_client.get(
        "/api/v1/catalogue/datasets", params={"limit": limit}
    ).status_code == 422


def test_catalogue_offset_cannot_be_negative(
    catalogue_client: TestClient,
) -> None:
    assert catalogue_client.get(
        "/api/v1/catalogue/datasets", params={"offset": -1}
    ).status_code == 422


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_catalogue_paths_reject_write_methods(
    catalogue_client: TestClient,
    method: str,
) -> None:
    response = getattr(catalogue_client, method)("/api/v1/catalogue/datasets")
    assert response.status_code == 405


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/catalogue/datasets",
        f"/api/v1/catalogue/datasets/{encode_dataset_ref('nged', 'middle')}",
        f"/api/v1/catalogue/datasets/{encode_dataset_ref('nged', 'middle')}/resources",
    ],
)
@pytest.mark.parametrize(
    ("method", "expected_status"),
    [("get", 200), ("post", 405), ("delete", 405)],
)
def test_catalogue_actual_method_matrix_is_get_only(
    catalogue_client: TestClient,
    path: str,
    method: str,
    expected_status: int,
) -> None:
    assert getattr(catalogue_client, method)(path).status_code == expected_status


def test_catalogue_preflight_does_not_advertise_writes(
    catalogue_client: TestClient,
) -> None:
    response = catalogue_client.options(
        "/api/v1/catalogue/datasets",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 405
    assert "POST" not in response.headers.get("access-control-allow-methods", "")


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/catalogue/datasets",
        f"/api/v1/catalogue/datasets/{encode_dataset_ref('nged', 'middle')}",
        f"/api/v1/catalogue/datasets/{encode_dataset_ref('nged', 'middle')}/resources",
    ],
)
@pytest.mark.parametrize("requested_method", ["GET", "POST", "DELETE"])
def test_catalogue_preflight_matrix_is_path_aware_and_get_only(
    catalogue_client: TestClient,
    path: str,
    requested_method: str,
) -> None:
    response = catalogue_client.options(
        path,
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": requested_method,
        },
    )
    assert response.status_code == 405
    assert "access-control-allow-methods" not in response.headers


def test_catalogue_trailing_slash_and_encoded_slash_do_not_broaden_routes(
    catalogue_client: TestClient,
) -> None:
    assert catalogue_client.get(
        "/api/v1/catalogue/datasets/", follow_redirects=False
    ).status_code in {
        307,
        308,
    }
    assert catalogue_client.get(
        "/api/v1/catalogue/datasets/not%2Fcaptured"
    ).status_code == 404
    assert catalogue_client.get(
        "/api/v1/catalogue/datasets/not-a-ref/unknown-child"
    ).status_code == 404
    near_miss_preflight = catalogue_client.options(
        "/api/v1/catalogue/datasets/not-a-ref/unknown-child",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert near_miss_preflight.status_code == 200
    assert "POST" in near_miss_preflight.headers["access-control-allow-methods"]


def test_catalogue_openapi_models_have_only_whitelisted_public_properties() -> None:
    schema = create_app(replace(config)).openapi()
    public_models = {
        name: value
        for name, value in schema["components"]["schemas"].items()
        if name.startswith("Catalogue")
    }
    serialised = json.dumps(public_models)
    for forbidden in FORBIDDEN_KEYS | {"current_attempt_safe_error", "source_value"}:
        assert forbidden not in serialised
    for path, operations in schema["paths"].items():
        if path.startswith("/api/v1/catalogue/"):
            assert set(operations) == {"get"}

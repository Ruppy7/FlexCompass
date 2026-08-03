"""API integration tests for the Phase 0 public surface."""

import importlib
import re

import app.db as app_db
import httpx
import pytest
from app.main import app
from app.seed_loader import load_example_portfolios


class TestHealthEndpoints:
    def test_root_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "service": "flexcompass",
            "version": "0.1.0",
            "seed": 42,
        }

    def test_api_health(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "data_status": (
                "verified_analytical_source_available_for_local_sync"
            ),
        }


def test_public_api_contains_only_verified_surfaces() -> None:
    paths = set(app.openapi()["paths"])
    assert paths == {
        "/",
        "/health",
        "/api/health",
        "/api/demo/portfolios",
        "/api/demo/analyse",
        "/api/demo/report",
        "/api/demo/asset-groups/generate",
        "/api/v1/outages/events",
        "/api/v1/outages/summary",
        "/api/v1/outages/events/{event_id}",
        "/api/v1/outages/snapshots",
        "/api/v1/catalogue/portals",
        "/api/v1/catalogue/portals/{portal_id}",
        "/api/v1/catalogue/datasets",
        "/api/v1/catalogue/datasets/{dataset_ref}",
        "/api/v1/catalogue/datasets/{dataset_ref}/resources",
        "/api/v1/catalogue/datasets/{dataset_ref}/evidence",
        "/api/v1/catalogue/datasets/{dataset_ref}/assessments",
        "/api/v1/catalogue/observations",
    }


def test_root_metadata_lists_the_complete_verified_public_surface(
    client,
) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["endpoints"] == [
        "/health",
        "/api/health",
        "/api/demo/portfolios",
        "/api/demo/analyse",
        "/api/demo/report",
        "/api/demo/asset-groups/generate",
        "/api/v1/outages/events",
        "/api/v1/outages/summary",
        "/api/v1/outages/events/{event_id}",
        "/api/v1/outages/snapshots",
        "/api/v1/catalogue/portals",
        "/api/v1/catalogue/portals/{portal_id}",
        "/api/v1/catalogue/datasets",
        "/api/v1/catalogue/datasets/{dataset_ref}",
        "/api/v1/catalogue/datasets/{dataset_ref}/resources",
        "/api/v1/catalogue/datasets/{dataset_ref}/evidence",
        "/api/v1/catalogue/datasets/{dataset_ref}/assessments",
        "/api/v1/catalogue/observations",
    ]


@pytest.mark.parametrize(
    "path",
    [
        "/api/sources",
        "/api/signals",
        "/api/market-rules",
        "/api/example-portfolios",
        "/api/analyse",
        "/api/report",
        "/api/zones",
        "/api/ingest/status",
    ],
)
def test_unverified_product_routes_are_retired(path: str) -> None:
    assert path not in app.openapi()["paths"]


def test_application_starts_without_opening_the_primary_database(
    isolated_api_client,
) -> None:
    client, test_db = isolated_api_client

    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["data_status"] == (
        "verified_analytical_source_available_for_local_sync"
    )
    assert not test_db.exists()


def test_injected_settings_govern_existing_outage_route_reads(client) -> None:
    response = client.get("/api/v1/outages/snapshots")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    "method",
    ["get", "head", "post", "put", "patch", "delete", "options"],
)
def test_legacy_catalogue_route_has_deterministic_migration_response(
    client,
    method: str,
) -> None:
    response = getattr(client, method)("/api/portal/datasets")
    assert response.status_code == 410
    if method != "head":
        assert response.json() == {
            "detail": "Use /api/v1/catalogue/datasets"
        }


def test_legacy_catalogue_cors_preflight_is_410_without_advertised_methods(
    client,
) -> None:
    response = client.options(
        "/api/portal/datasets",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 410
    assert response.json() == {"detail": "Use /api/v1/catalogue/datasets"}
    assert "access-control-allow-methods" not in response.headers


def test_legacy_catalogue_trailing_alias_redirects_but_subpaths_are_absent(
    client,
) -> None:
    trailing = client.get(
        "/api/portal/datasets/",
        follow_redirects=False,
    )
    assert trailing.status_code in {307, 308}
    assert client.get("/api/portal/datasets/private").status_code == 404
    trailing_preflight = client.options(
        "/api/portal/datasets/",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert trailing_preflight.status_code == 410
    assert "access-control-allow-methods" not in trailing_preflight.headers
    subpath_preflight = client.options(
        "/api/portal/datasets/private",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert subpath_preflight.status_code == 200
    assert "POST" in subpath_preflight.headers["access-control-allow-methods"]


@pytest.fixture
def demo_portfolio() -> dict[str, object]:
    return load_example_portfolios()[0].model_dump(mode="json")


def test_legacy_portfolios_route_is_absent(client) -> None:
    assert client.get("/api/portfolios").status_code == 404


def test_demo_portfolios_are_explicitly_synthetic(client) -> None:
    response = client.get("/api/demo/portfolios")
    assert response.status_code == 200
    payload = response.json()
    assert payload["workflow_kind"] == "synthetic_demo"
    assert payload["portal_data_used"] is False
    assert all(
        asset["source"] == "synthetic"
        for portfolio in payload["items"]
        for asset in portfolio["assets"]
    )
    assert all(
        "synthetic" in portfolio["portfolio_name"].lower()
        for portfolio in payload["items"]
    )


def test_demo_report_states_no_portal_data_is_used(
    client,
    demo_portfolio,
) -> None:
    response = client.post(
        "/api/demo/report",
        json={"portfolio": demo_portfolio},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["workflow_kind"] == "synthetic_demo"
    assert payload["portal_data_used"] is False
    assert payload["markdown"].startswith(
        "# Synthetic Flexibility Fit Demonstration"
    )
    assert (
        "no live or current portal data is used."
        in payload["markdown"].lower()
    )
    assert "synthetic-only" in payload["markdown"].lower()
    assert re.search(
        (
            r"\buses?\b[^.\n]{0,40}"
            r"\b(?:public|curated|live|current)\b"
            r"[^.\n]{0,20}\bdata\b"
        ),
        payload["markdown"],
        flags=re.IGNORECASE,
    ) is None


@pytest.mark.parametrize("endpoint", ["analyse", "report"])
def test_demo_rejects_real_asset_source(
    client,
    demo_portfolio,
    endpoint: str,
) -> None:
    demo_portfolio["assets"][0]["source"] = "real"
    response = client.post(
        f"/api/demo/{endpoint}",
        json={"portfolio": demo_portfolio},
    )
    assert response.status_code == 422
    assert response.json()["workflow_kind"] == "synthetic_demo"
    assert response.json()["portal_data_used"] is False


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/demo/portfolios"),
        ("post", "/api/demo/analyse"),
        ("post", "/api/demo/report"),
        ("post", "/api/demo/asset-groups/generate"),
    ],
)
def test_every_demo_response_is_labelled(
    client,
    demo_portfolio: dict[str, object],
    method: str,
    path: str,
) -> None:
    body = (
        {"asset_type": "battery", "count": 2, "portal_id": "nged"}
        if path.endswith("/generate")
        else {"portfolio": demo_portfolio}
    )
    if method == "get":
        body = None
    kwargs = {"json": body} if body is not None else {}
    response = getattr(client, method)(path, **kwargs)
    assert response.json()["workflow_kind"] == "synthetic_demo"
    assert response.json()["portal_data_used"] is False


def test_demo_handlers_never_open_database_or_network(
    client,
    demo_portfolio,
    monkeypatch,
) -> None:
    def unexpected(*args, **kwargs):
        raise AssertionError("demo attempted external I/O")

    test_client_send = client.send
    monkeypatch.setattr(app_db.sqlite3, "connect", unexpected)
    monkeypatch.setattr(httpx.Client, "send", unexpected)
    monkeypatch.setattr(httpx.AsyncClient, "send", unexpected)
    monkeypatch.setattr(client, "send", test_client_send)

    assert client.get("/api/demo/portfolios").status_code == 200
    assert client.post(
        "/api/demo/analyse",
        json={"portfolio": demo_portfolio},
    ).status_code == 200
    assert client.post(
        "/api/demo/report",
        json={"portfolio": demo_portfolio},
    ).status_code == 200
    assert client.post(
        "/api/demo/asset-groups/generate",
        json={"asset_type": "battery", "count": 2, "portal_id": "nged"},
    ).status_code == 200


def test_demo_internal_error_keeps_labels_and_redaction(
    client,
    demo_portfolio,
    monkeypatch,
) -> None:
    demo_routes = importlib.import_module("app.demo_routes")
    monkeypatch.setattr(
        demo_routes,
        "analyse_synthetic_portfolio",
        lambda *_: (_ for _ in ()).throw(RuntimeError("private-value")),
    )
    response = client.post(
        "/api/demo/analyse",
        json={"portfolio": demo_portfolio},
    )
    assert response.status_code == 500
    assert response.json()["workflow_kind"] == "synthetic_demo"
    assert response.json()["portal_data_used"] is False
    assert "private-value" not in response.text

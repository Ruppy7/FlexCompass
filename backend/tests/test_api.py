"""API integration tests for the Phase 0 public surface."""

import pytest
from app.main import app


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
            "data_status": "no_verified_analytical_data",
        }


def test_phase_zero_public_api_contains_health_only() -> None:
    paths = set(app.openapi()["paths"])
    assert paths == {"/", "/health", "/api/health"}


@pytest.mark.parametrize(
    "path",
    [
        "/api/sources",
        "/api/signals",
        "/api/market-rules",
        "/api/example-portfolios",
        "/api/analyse",
        "/api/report",
        "/api/portal/datasets",
        "/api/zones",
        "/api/ingest/status",
    ],
)
def test_unverified_product_routes_are_retired(path: str) -> None:
    assert path not in app.openapi()["paths"]


def test_application_starts_without_opening_a_database(
    isolated_api_client,
) -> None:
    client, test_db = isolated_api_client

    assert client.get("/api/health").status_code == 200
    assert not test_db.exists()

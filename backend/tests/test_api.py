"""API integration tests — exercise endpoints against real DB."""

from pathlib import Path


class TestHealthEndpoints:
    def test_root_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"

    def test_api_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestPortalEndpoints:
    def test_portal_datasets(self, client):
        r = client.get("/api/portal/datasets")
        assert r.status_code == 200
        data = r.json()
        datasets = data["items"]
        assert data["total"] == 4
        assert len(datasets) == 4
        assert all("id" in d for d in datasets)

    def test_portal_dataset_by_id(self, client):
        r = client.get("/api/portal/datasets/catalog_nged")
        assert r.status_code == 200
        assert r.json()["id"] == "catalog_nged"

    def test_portal_dataset_fields(self, client):
        r = client.get("/api/portal/datasets/catalog_nged/fields")
        assert r.status_code == 200
        assert "fields" in r.json()


class TestZoneEndpoints:
    def test_list_zones(self, client):
        r = client.get("/api/zones")
        assert r.status_code == 200
        data = r.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_filter_zones_by_dso(self, client):
        r = client.get("/api/zones?dso=NGED")
        assert r.status_code == 200
        data = r.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_get_zone_by_id(self, client):
        r = client.get("/api/zones/not-yet-normalised")
        assert r.status_code == 404

    def test_zone_not_found(self, client):
        r = client.get("/api/zones/nonexistent")
        assert r.status_code == 404


class TestSignalEndpoints:
    def test_list_signals(self, client):
        r = client.get("/api/signals")
        assert r.status_code == 200
        data = r.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_signals_by_zone(self, client):
        r = client.get("/api/signals/by-zone/not-yet-normalised")
        assert r.status_code == 200
        assert r.json() == []


class TestAnalysisEndpoints:
    def test_list_portfolios(self, client):
        r = client.get("/api/portfolios")
        assert r.status_code == 200
        assert len(r.json()) >= 2

    def test_analyse_portfolio(self, client):
        portfolio = {
            "portfolio_id": "test_001",
            "portfolio_name": "Test Portfolio",
            "assets": [{
                "source": "synthetic",
                "asset_type": "ev_charger",
                "asset_count": 1000,
                "rated_power_kw": 7,
                "controllable_power_kw": 4.5,
                "availability_percent": 0.03,
                "response_reliability_percent": 0.85,
                "supported_service_types": ["demand_turn_down"],
                "regional_distribution": {"NGED": 0.5},
                "postcode_distribution": {},
                "baseline_assumption": "test",
                "metering_assumption": "test",
                "operational_notes": [],
            }],
        }
        r = client.post("/api/analyse", json={"portfolio": portfolio})
        assert r.status_code == 200
        data = r.json()
        assert "assessments" in data
        assert data["signals_considered"] == 0
        assert data["assessments"] == []

    def test_report_generation(self, client):
        portfolio = {
            "portfolio_id": "test_002",
            "portfolio_name": "Test Report",
            "assets": [{
                "source": "synthetic",
                "asset_type": "battery",
                "asset_count": 50,
                "rated_power_kw": 10,
                "controllable_power_kw": 6,
                "availability_percent": 0.5,
                "response_reliability_percent": 0.9,
                "supported_service_types": ["demand_turn_down", "generation_turn_up"],
                "regional_distribution": {"SPEN": 0.8},
                "postcode_distribution": {},
                "baseline_assumption": "test",
                "metering_assumption": "test",
                "operational_notes": [],
            }],
        }
        r = client.post("/api/report", json={"portfolio": portfolio})
        assert r.status_code == 200
        data = r.json()
        assert "markdown" in data
        assert "Flexibility Fit Report" in data["markdown"]


class TestAssetGroupEndpoints:
    def test_list_asset_groups(self, client):
        r = client.get("/api/asset-groups")
        assert r.status_code == 200
        groups = r.json()
        assert len(groups) >= 4

    def test_generate_asset_group(self, client):
        r = client.post("/api/asset-groups/generate",
                       json={"asset_type": "battery", "count": 500, "portal_id": "nged"})
        assert r.status_code == 200
        data = r.json()
        assert data["asset_group"]["asset_type"] == "battery"
        assert data["asset_group"]["source"] == "synthetic"
        assert data["estimated_available_kw"] > 0


class TestIngestEndpoints:
    def test_ingest_status(self, client):
        r = client.get("/api/ingest/status")
        assert r.status_code == 200
        data = r.json()
        assert "ingested_tables" in data
        assert data["total_records"] == 0


class TestDbStatsEndpoint:
    def test_db_stats(self, client):
        r = client.get("/api/db/stats")
        assert r.status_code == 200
        data = r.json()
        assert data["source"] == "db"
        assert "tables" in data


def test_application_database_is_isolated(isolated_api_client) -> None:
    client, test_db = isolated_api_client
    repository_db = Path(__file__).resolve().parents[2] / "data" / "flexcompass.db"

    assert client.get("/api/health").status_code == 200
    assert test_db.exists()
    assert test_db.resolve() != repository_db.resolve()

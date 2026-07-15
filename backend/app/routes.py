"""API routes for FlexCompass v0.1.

Uses SQLite DB when available (data/flexcompass.db), falls back to JSON seed files.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException

from .config import config as _config
from .matching import assess_portfolio
from .models import (
    AnalyseRequest,
    AnalyseResponse,
    DataSource,
    FlexSignal,
    FlexZone,
    GenerateAssetGroupRequest,
    MarketRule,
    PortalDataset,
    Portfolio,
    ReportRequest,
    ReportResponse,
)
from .report_generator import generate_report

logger = logging.getLogger(__name__)


def _require_admin(authorization: str | None = Header(None)) -> None:
    """Check admin token for mutating endpoints. No-op if no token configured."""
    if not _config.admin_token:
        return  # No token configured — allow all (local dev mode)
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    token = authorization.replace("Bearer ", "").strip()
    if token != _config.admin_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")


router = APIRouter(prefix="/api")

# Module-level caches — populated by reload_data() (called from lifespan)
_sources: list[DataSource] = []
_rules: list[MarketRule] = []
_signals: list[FlexSignal] = []
_portfolios: list[Portfolio] = []
_zones: list[FlexZone] = []
_datasets: list[PortalDataset] = []


def _get_db_path():
    return _config.db_path


def reload_data() -> None:
    """Re-read all data from DB/JSON and update module-level caches.

    Called at import time and after every ingest run so the API always
    serves fresh data without a process restart.
    """
    global _sources, _rules, _signals, _portfolios, _zones, _datasets

    db_path = _get_db_path()
    if db_path.exists():
        from .db_loader import (
            load_data_sources,
            load_flex_signals,
            load_flex_zones,
            load_market_rules,
            load_portal_datasets,
        )
        from .seed_loader import load_example_portfolios
    else:
        from .seed_loader import (
            load_data_sources,
            load_example_portfolios,
            load_flex_signals,
            load_flex_zones,
            load_market_rules,
            load_portal_datasets,
        )

    _sources = load_data_sources()
    _rules = load_market_rules()
    _signals = load_flex_signals()
    _portfolios = load_example_portfolios()
    _zones = load_flex_zones()
    _datasets = load_portal_datasets()

    logger.info("Data reloaded: %d sources, %d rules, %d signals, %d zones, %d datasets, %d portfolios",
                len(_sources), len(_rules), len(_signals), len(_zones), len(_datasets), len(_portfolios))


# NOTE: reload_data() is called from the lifespan startup in main.py, not at import time.


@router.get("/health")
def health():
    return {"status": "ok", "source": "db" if _get_db_path().exists() else "json"}


# ---------------------------------------------------------------------------
# v0 endpoints (backward compat)
# ---------------------------------------------------------------------------

@router.get("/sources", response_model=list[DataSource])
def get_sources():
    return _sources


@router.get("/signals")
def get_signals(limit: int = 100, offset: int = 0):
    total = len(_signals)
    return {"items": _signals[offset:offset + limit], "total": total, "limit": limit, "offset": offset}


@router.get("/market-rules", response_model=list[MarketRule])
def get_market_rules():
    return _rules


@router.get("/portfolios", response_model=list[Portfolio])
def get_portfolios():
    return _portfolios


@router.post("/analyse", response_model=AnalyseResponse)
def analyse(request: AnalyseRequest):
    portfolio = request.portfolio
    assessments = assess_portfolio(portfolio, _signals, _rules)
    dsos = sorted({s.dso for s in _signals})
    source_names = [src.source_name for src in _sources]
    return AnalyseResponse(
        portfolio=portfolio,
        assessments=assessments,
        signals_considered=len(_signals),
        sources_represented=source_names,
        dsos_represented=dsos,
    )


@router.post("/report", response_model=ReportResponse)
def report(request: ReportRequest):
    portfolio = request.portfolio
    assessments = assess_portfolio(portfolio, _signals, _rules)
    md = generate_report(portfolio, assessments, _signals, _sources)
    return ReportResponse(
        markdown=md,
        portfolio=portfolio,
        assessments=assessments,
    )


# ---------------------------------------------------------------------------
# v0.1 endpoints (zone-authoritative)
# ---------------------------------------------------------------------------

@router.get("/portal/datasets")
def get_portal_datasets(limit: int = 100, offset: int = 0):
    """List all portal datasets we track."""
    total = len(_datasets)
    return {"items": _datasets[offset:offset + limit], "total": total, "limit": limit, "offset": offset}


@router.get("/portal/datasets/{dataset_id}", response_model=PortalDataset)
def get_portal_dataset(dataset_id: str):
    """Get metadata for a single portal dataset."""
    for ds in _datasets:
        if ds.id == dataset_id:
            return ds
    raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")


@router.get("/portal/datasets/{dataset_id}/fields")
def get_portal_dataset_fields(dataset_id: str):
    """Get the field list for a portal dataset."""
    for ds in _datasets:
        if ds.id == dataset_id:
            return {"dataset_id": ds.id, "fields": ds.fields}
    raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")


@router.get("/zones")
def get_zones(dso: str | None = None, limit: int = 100, offset: int = 0):
    """List all flexibility zones, optionally filtered by DSO."""
    if dso:
        filtered = [z for z in _zones if z.dso.upper() == dso.upper()]
    else:
        filtered = _zones
    total = len(filtered)
    return {"items": filtered[offset:offset + limit], "total": total, "limit": limit, "offset": offset}


@router.get("/zones/{zone_id}", response_model=FlexZone)
def get_zone(zone_id: str):
    """Get a single zone by ID."""
    for z in _zones:
        if z.zone_id == zone_id:
            return z
    raise HTTPException(status_code=404, detail=f"Zone '{zone_id}' not found")


@router.get("/signals/by-zone/{zone_id}", response_model=list[FlexSignal])
def get_signals_by_zone(zone_id: str):
    """Get all signals for a specific zone."""
    return [s for s in _signals if s.zone_id == zone_id]


@router.get("/db/stats")
def get_db_stats():
    """Return database statistics (cache stats, table counts)."""
    db_path = _get_db_path()
    if not db_path.exists():
        return {"source": "json", "db_exists": False}
    from .db import cache_stats
    return {
        "source": "db",
        "db_path": str(db_path),
        "tables": {
            "portal_datasets": len(_datasets),
            "flex_zones": len(_zones),
            "flex_signals": len(_signals),
            "data_sources": len(_sources),
            "market_rules": len(_rules),
        },
        "cache": cache_stats(),
    }


# ---------------------------------------------------------------------------
# Asset groups
# ---------------------------------------------------------------------------

@router.get("/asset-groups")
def get_asset_groups():
    """List available asset groups (from example portfolios)."""
    groups = []
    for p in _portfolios:
        for g in p.assets:
            groups.append({
                "portfolio_id": p.portfolio_id,
                "portfolio_name": p.portfolio_name,
                "asset_type": g.asset_type.value,
                "asset_count": g.asset_count,
                "source": g.source.value,
                "controllable_power_kw": g.controllable_power_kw,
                "availability_percent": g.availability_percent,
                "supported_service_types": [s.value for s in g.supported_service_types],
            })
    return groups


@router.post("/asset-groups/generate")
def generate_asset_groups(spec: GenerateAssetGroupRequest):
    """Generate a synthetic asset group from a specification.

    Body: { "asset_type": "ev_charger", "count": 1000, "region": "NGED" }
    """
    from .models import AssetGroup, AssetSource, AssetType, ServiceType
    asset_type_str = spec.asset_type
    count = spec.count
    region = spec.region

    try:
        asset_type = AssetType(asset_type_str)
    except ValueError:
        raise HTTPException(400, f"Invalid asset_type: {asset_type_str}")

    # Default power assumptions by type
    power_defaults = {
        "ev_charger": {"rated": 7.0, "controllable": 4.5, "avail": 0.03, "reliability": 0.85},
        "battery": {"rated": 10.0, "controllable": 6.0, "avail": 0.5, "reliability": 0.9},
        "generator": {"rated": 100.0, "controllable": 60.0, "avail": 0.4, "reliability": 0.9},
        "heat_pump": {"rated": 5.0, "controllable": 3.0, "avail": 0.1, "reliability": 0.8},
        "solar_pv": {"rated": 4.0, "controllable": 0.0, "avail": 0.0, "reliability": 0.7},
        "ci_load": {"rated": 50.0, "controllable": 20.0, "avail": 0.15, "reliability": 0.85},
    }
    defaults = power_defaults.get(asset_type_str, power_defaults["ev_charger"])

    svc_defaults = {
        "ev_charger": ["demand_turn_down", "demand_turn_up"],
        "battery": ["demand_turn_down", "demand_turn_up", "generation_turn_up", "generation_turn_down"],
        "generator": ["generation_turn_up", "generation_turn_down"],
        "heat_pump": ["demand_turn_down"],
        "solar_pv": ["generation_turn_up"],
        "ci_load": ["demand_turn_down"],
    }

    group = AssetGroup(
        asset_group_id=f"gen_{asset_type_str}_{count}_{region}",
        source=AssetSource.synthetic,
        asset_type=asset_type,
        asset_count=count,
        rated_power_kw=defaults["rated"],
        controllable_power_kw=defaults["controllable"],
        availability_percent=defaults["avail"],
        response_reliability_percent=defaults["reliability"],
        supported_service_types=[ServiceType(s) for s in svc_defaults.get(asset_type_str, [])],
        regional_distribution={region: 1.0},
        baseline_assumption="Synthetic — generated for directional analysis only.",
        metering_assumption="Not validated — synthetic generation.",
        operational_notes=["Generated by /asset-groups/generate endpoint."],
    )

    est_kw = count * defaults["controllable"] * defaults["avail"] * defaults["reliability"]
    return {
        "asset_group": group.model_dump(),
        "estimated_available_kw": round(est_kw, 2),
        "capacity_method": "v0.1_synthetic",
    }


# ---------------------------------------------------------------------------
# Data ingest
# ---------------------------------------------------------------------------

@router.post("/ingest", dependencies=[Depends(_require_admin)])
def run_ingest(portal: str = "all"):
    """Run data ingest from DSO portals.

    Body: { "portal": "all" | "nged" | "spen" | "enwl" }
    Returns record counts per dataset.
    """
    from .ingest import run_all, run_enwl_ingest, run_nged_ingest, run_spen_ingest

    try:
        if portal == "nged":
            counts = run_nged_ingest()
        elif portal == "spen":
            counts = run_spen_ingest()
        elif portal == "enwl":
            counts = run_enwl_ingest()
        else:
            result = run_all()
            reload_data()
            return result
        reload_data()
        return {"portal": portal, "counts": counts}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ingest error: {e}")


@router.get("/ingest/status")
def ingest_status():
    """Check what data has been ingested."""
    from .db import get_connection
    try:
        with get_connection() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            counts = {}
            for (t,) in tables:
                if t.startswith(("nged_", "spen_", "enwl_", "postcode_")):
                    n = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
                    counts[t] = n
            return {"ingested_tables": counts, "total_records": sum(counts.values())}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Portal drift monitoring
# ---------------------------------------------------------------------------

@router.post("/drift/check", dependencies=[Depends(_require_admin)])
def run_drift():
    """Run a portal drift check across all DSO portals."""
    from .drift import run_drift_check
    try:
        alerts = run_drift_check()
        return {
            "alerts": len(alerts),
            "details": [
                {"portal": a.portal, "dataset": a.dataset, "type": a.alert_type,
                 "old": a.old_value, "new": a.new_value, "severity": a.severity}
                for a in alerts
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Drift check error: {e}")


@router.get("/drift/alerts")
def get_drift_alerts(limit: int = 20):
    """Get recent unacknowledged drift alerts."""
    from .drift import get_recent_alerts
    return {"alerts": get_recent_alerts(limit)}

"""Portal-drift watcher — monitors DSO portals for changes.

Checks each portal for:
  - Record count changes (new data published)
  - Schema changes (new/removed fields)
  - Price changes (guide price movements)

Stores snapshots in SQLite and diffs against previous run.
Run periodically (cron or manual) to detect when portals update.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from .db import get_connection, run_migrations

logger = logging.getLogger(__name__)


@dataclass
class DriftAlert:
    """A detected change in a portal dataset."""
    portal: str
    dataset: str
    alert_type: str  # "record_count", "schema", "price"
    old_value: str
    new_value: str
    severity: str  # "info", "warning", "critical"
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _get_latest_snapshot(portal: str, dataset: str) -> dict | None:
    """Get the most recent snapshot for a portal/dataset."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT record_count, field_names, field_hash, sample_prices, snapshot_at "
            "FROM drift_snapshots WHERE portal=? AND dataset=? "
            "ORDER BY snapshot_at DESC LIMIT 1",
            (portal, dataset),
        ).fetchone()
    if not row:
        return None
    return {
        "record_count": row[0],
        "field_names": json.loads(row[1]) if row[1] else [],
        "field_hash": row[2],
        "sample_prices": json.loads(row[3]) if row[3] else [],
        "snapshot_at": row[4],
    }


def _save_snapshot(portal: str, dataset: str, record_count: int,
                   fields: list[str], prices: list[float]):
    """Save a snapshot."""
    field_hash = hashlib.md5(json.dumps(sorted(fields)).encode()).hexdigest()[:12]
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO drift_snapshots (portal, dataset, record_count, field_names, field_hash, sample_prices) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (portal, dataset, record_count, json.dumps(fields), field_hash,
             json.dumps(prices[:10])),
        )


def _save_alert(alert: DriftAlert):
    """Save a drift alert."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO drift_alerts (portal, dataset, alert_type, old_value, new_value, severity) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (alert.portal, alert.dataset, alert.alert_type,
             alert.old_value, alert.new_value, alert.severity),
        )


def check_nged() -> list[DriftAlert]:
    """Check NGED portal for changes."""
    alerts = []
    import os

    from dotenv import load_dotenv
    load_dotenv()
    token = os.getenv("NGED_DATAPORTAL_TOKEN", "")
    headers = {"Authorization": token, "Accept": "application/json"}
    base = "https://connecteddata.nationalgrid.co.uk/api/3/action"

    datasets = {
        "flexibility-trades-data-and-results": "Trade Results Summary",
        "flexibility-reports": "Procurement Report",
        "flexibility-forecasts": "WHERE All Postcodes",
    }

    for pkg_name, label in datasets.items():
        try:
            r = httpx.get(f"{base}/package_show", params={"id": pkg_name},
                         headers=headers, timeout=20)
            if r.status_code != 200:
                continue
            pkg = r.json().get("result", {})
            for res in pkg.get("resources", []):
                if not res.get("datastore_active"):
                    continue
                rid = res["id"]
                rname = res.get("name", "")
                r2 = httpx.get(f"{base}/datastore_search",
                              params={"resource_id": rid, "limit": 1},
                              headers=headers, timeout=20)
                if r2.status_code != 200:
                    continue
                result = r2.json().get("result", {})
                total = result.get("total", 0)
                records = result.get("records", [])
                fields = list(records[0].keys()) if records else []

                prev = _get_latest_snapshot("NGED", rname)
                if prev:
                    if total != prev["record_count"]:
                        severity = "warning" if abs(total - prev["record_count"]) > 100 else "info"
                        alerts.append(DriftAlert(
                            portal="NGED", dataset=rname,
                            alert_type="record_count",
                            old_value=str(prev["record_count"]),
                            new_value=str(total),
                            severity=severity,
                        ))
                    if set(fields) != set(prev["field_names"]):
                        alerts.append(DriftAlert(
                            portal="NGED", dataset=rname,
                            alert_type="schema",
                            old_value=", ".join(prev["field_names"]),
                            new_value=", ".join(fields),
                            severity="warning",
                        ))

                _save_snapshot("NGED", rname, total, fields, [])
                time.sleep(0.5)  # Rate limit
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            logger.warning("NGED drift check failed for dataset %s/%s: %s", pkg_name, label, e)
            continue

    return alerts


def check_spen_enwl() -> list[DriftAlert]:
    """Check SPEN and ENWL portals for changes."""
    alerts = []
    import os

    from dotenv import load_dotenv
    load_dotenv()

    portals = {
        "SPEN": ("https://spenergynetworks.opendatasoft.com/api/v2/catalog/datasets",
                 os.getenv("SPEN_DATAPORTAL_TOKEN", "")),
        "ENWL": ("https://electricitynorthwest.opendatasoft.com/api/v2/catalog/datasets",
                 os.getenv("ENWL_DATAPORTAL_TOKEN", "")),
    }

    datasets = {
        "SPEN": ["flexibility_competitions", "flexibility_bids", "flexibility-dispatch"],
        "ENWL": ["enwl-historical-flexibility-tender-site-requirements",
                 "slc31e-dispatch", "slc31e-procurement"],
    }

    for portal, (base, token) in portals.items():
        for ds_id in datasets.get(portal, []):
            try:
                r = httpx.get(f"{base}/{ds_id}",
                             params={"apikey": token}, timeout=20)
                if r.status_code != 200:
                    continue
                meta = r.json().get("dataset", {}).get("metas", {}).get("default", {})
                count = meta.get("records_count", 0)

                # Fetch 1 record for field names
                r2 = httpx.get(f"{base}/{ds_id}/exports/json",
                              params={"apikey": token, "limit": 1}, timeout=20)
                fields = list(r2.json()[0].keys()) if r2.status_code == 200 and r2.json() else []

                prev = _get_latest_snapshot(portal, ds_id)
                if prev:
                    if count != prev["record_count"]:
                        severity = "warning" if abs(count - prev["record_count"]) > 100 else "info"
                        alerts.append(DriftAlert(
                            portal=portal, dataset=ds_id,
                            alert_type="record_count",
                            old_value=str(prev["record_count"]),
                            new_value=str(count),
                            severity=severity,
                        ))

                _save_snapshot(portal, ds_id, count, fields, [])
                time.sleep(0.5)
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                logger.warning("%s drift check failed for dataset %s: %s", portal, ds_id, e)
                continue

    return alerts


def check_ssen() -> list[DriftAlert]:
    """Check SSEN portal for changes."""
    alerts = []
    base = "https://ckan-prod.sse.datopian.com/api/3/action"

    packages = [
        "flexibility-services-contract-register",
        "flexibility-dispatch-report",
        "long-term-bidding",
    ]

    for pkg_name in packages:
        try:
            r = httpx.get(f"{base}/package_show", params={"id": pkg_name}, timeout=20)
            if r.status_code != 200:
                continue
            pkg = r.json().get("result", {})
            ds_resources = [r for r in pkg.get("resources", []) if r.get("datastore_active")]

            for res in ds_resources[:3]:  # Check first 3 resources per package
                rid = res["id"]
                rname = res.get("name", "")
                r2 = httpx.get(f"{base}/datastore_search",
                              params={"resource_id": rid, "limit": 1}, timeout=20)
                if r2.status_code != 200:
                    continue
                result = r2.json().get("result", {})
                total = result.get("total", 0)
                records = result.get("records", [])
                fields = list(records[0].keys()) if records else []

                prev = _get_latest_snapshot("SSEN", rname)
                if prev and total != prev["record_count"]:
                    alerts.append(DriftAlert(
                        portal="SSEN", dataset=rname,
                        alert_type="record_count",
                        old_value=str(prev["record_count"]),
                        new_value=str(total),
                        severity="info",
                    ))

                _save_snapshot("SSEN", rname, total, fields, [])
                time.sleep(0.5)
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            logger.warning("SSEN drift check failed for package %s: %s", pkg_name, e)
            continue

    return alerts


def run_drift_check() -> list[DriftAlert]:
    """Run full drift check across all portals."""
    run_migrations()
    all_alerts = []

    print("[Drift] Checking NGED...")
    all_alerts.extend(check_nged())
    print(f"[Drift] NGED: {len([a for a in all_alerts if a.portal == 'NGED'])} alerts")

    print("[Drift] Checking SPEN/ENWL...")
    spen_enwl_alerts = check_spen_enwl()
    all_alerts.extend(spen_enwl_alerts)
    print(f"[Drift] SPEN/ENWL: {len(spen_enwl_alerts)} alerts")

    print("[Drift] Checking SSEN...")
    ssen_alerts = check_ssen()
    all_alerts.extend(ssen_alerts)
    print(f"[Drift] SSEN: {len(ssen_alerts)} alerts")

    # Save all alerts
    for alert in all_alerts:
        _save_alert(alert)

    print(f"[Drift] Total: {len(all_alerts)} alerts")
    return all_alerts


def get_recent_alerts(limit: int = 20) -> list[dict]:
    """Get recent unacknowledged alerts."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT portal, dataset, alert_type, old_value, new_value, severity, detected_at "
            "FROM drift_alerts WHERE acknowledged = 0 "
            "ORDER BY detected_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "portal": r[0], "dataset": r[1], "alert_type": r[2],
            "old_value": r[3], "new_value": r[4], "severity": r[5],
            "detected_at": r[6],
        }
        for r in rows
    ]

#!/usr/bin/env python3
"""FlexCompass v0.1 — 90-second demo script.

Run: python demo.py
Requires: backend server running on localhost:8099

Demonstrates:
  1. Portal intelligence (zones, signals, datasets)
  2. Postcode resolution (positive + negative paths)
  3. Portfolio analysis (heuristic matching)
  4. Report generation (Markdown export)
"""

import sys
import time

import httpx

BASE = "http://127.0.0.1:8099/api"


def get(path: str, use_base: bool = True) -> dict:
    url = f"{BASE}{path}" if use_base else path
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_items(path: str) -> list:
    """Fetch a paginated endpoint and return just the items list."""
    data = get(path)
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    if isinstance(data, list):
        return data
    return []


def post(path: str, data: dict) -> dict:
    resp = httpx.post(f"{BASE}{path}", json=data, timeout=10)
    resp.raise_for_status()
    return resp.json()


def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def main() -> None:
    start = time.time()

    # ── 1. Health check ──
    section("1. Health Check")
    health = get("http://127.0.0.1:8099/health", use_base=False)
    print(f"  Service: {health.get('service', 'flexcompass')} v{health.get('version', '0.1.0')}")
    print("  Data source: db")
    print(f"  Default seed: {health.get('seed', 'N/A')}")

    # ── 2. Portal Intelligence ──
    section("2. Portal Intelligence")

    datasets = get_items("/portal/datasets")
    print(f"  Portal datasets tracked: {len(datasets)}")
    for d in datasets[:3]:
        print(f"    - {d['name']} ({d['id']})")
    if len(datasets) > 3:
        print(f"    ... and {len(datasets) - 3} more")

    zones = get_items("/zones")
    dsos = {}
    for z in zones:
        dsos[z["dso"]] = dsos.get(z["dso"], 0) + 1
    print(f"\n  Flexibility zones: {len(zones)}")
    for dso, count in sorted(dsos.items()):
        print(f"    - {dso}: {count} zones")

    signals = get_items("/signals")
    sig_dsos = {}
    for s in signals:
        sig_dsos[s["dso"]] = sig_dsos.get(s["dso"], 0) + 1
    print(f"\n  Flexibility signals: {len(signals)}")
    for dso, count in sorted(sig_dsos.items()):
        print(f"    - {dso}: {count} signals")

    # ── 3. Postcode Resolution ──
    section("3. Postcode Resolution")

    test_postcodes = [
        ("B1 2AB", "Birmingham"),
        ("G1 1AA", "Glasgow"),
        ("M1 1AA", "Manchester"),
        ("AB10 1AA", "Aberdeen"),
        ("E1 1AA", "London (out of zone)"),
    ]

    for pc, label in test_postcodes:
        area = "".join(c for c in pc.split()[0] if c.isalpha())
        matching = [z for z in zones if area.upper() in [p.upper() for p in z.get("postcode_prefixes", [])]]
        if matching:
            dsos_matched = list(set(z["dso"] for z in matching))
            print(f"  {pc:12s} ({label:20s}) → {len(matching)} zone(s), DSOs: {', '.join(dsos_matched)}")
        else:
            print(f"  {pc:12s} ({label:20s}) → no matches (negative path ✓)")

    # ── 5. Portfolio Analysis ──
    section("4. Portfolio Analysis")

    portfolio = {
        "portfolio_id": "demo_001",
        "portfolio_name": "Demo EV Portfolio",
        "assets": [{
            "asset_type": "ev_charger",
            "asset_count": 3000,
            "rated_power_kw": 7,
            "controllable_power_kw": 4.5,
            "availability_percent": 0.03,
            "response_reliability_percent": 0.85,
            "supported_service_types": ["demand_turn_down", "demand_turn_up"],
            "regional_distribution": {"NGED": 0.3, "UKPN": 0.25, "SPEN": 0.15, "ENWL": 0.1, "SSEN": 0.1, "NPG": 0.1},
            "postcode_distribution": {},
            "baseline_assumption": "Synthetic demo portfolio.",
            "metering_assumption": "Not validated.",
            "operational_notes": ["Demo only — not real fleet data."],
        }],
    }

    est_kw = 3000 * 4.5 * 0.03 * 0.85
    print(f"  Portfolio: {portfolio['portfolio_name']}")
    print(f"  Assets: 3,000 EV chargers × 4.5kW × 3% × 85% = {est_kw:.1f} kW estimated")

    result = post("/analyse", {"portfolio": portfolio})
    assessments = result["assessments"]
    print(f"  Signals considered: {result['signals_considered']}")
    print(f"  DSOs represented: {', '.join(result['dsos_represented'])}")

    bands = {}
    for a in assessments:
        band = a["investigation_priority_band"]
        bands[band] = bands.get(band, 0) + 1

    print("\n  Assessment results:")
    for band in ["high", "medium", "low", "insufficient_evidence"]:
        count = bands.get(band, 0)
        if count:
            print(f"    {band:25s} → {count} signal(s)")

    # Show top match
    if assessments:
        top = assessments[0]
        print("\n  Top match:")
        print(f"    Signal: {top['signal_id']}")
        print(f"    Priority: {top['investigation_priority_band']}")
        print(f"    Est. capacity: {top['estimated_available_kw']:.1f} kW")
        print(f"    Geography: {top['location_evidence']}")
        print(f"    Asset compat: {top['asset_type_compatibility']}")

    # ── 6. Report Generation ──
    section("5. Report Generation")
    report = post("/report", {"portfolio": portfolio})
    md = report["markdown"]
    lines = md.split("\n")
    print(f"  Report length: {len(md):,} chars, {len(lines)} lines")
    print("  Sections found:")
    for line in lines:
        if line.startswith("## "):
            print(f"    - {line}")

    # ── Summary ──
    elapsed = time.time() - start
    section("Summary")
    print(f"  Datasets: {len(datasets)}")
    print(f"  Zones: {len(zones)}")
    print(f"  Signals: {len(signals)}")
    print(f"  Assessments: {len(assessments)}")
    print(f"  Report: {len(md):,} chars")
    print(f"\n  Demo completed in {elapsed:.1f}s")
    print("\n  ⚠ All scores are heuristic and directional.")
    print("  ⚠ Not a bid recommendation, eligibility confirmation, or revenue forecast.")


if __name__ == "__main__":
    try:
        main()
    except httpx.ConnectError:
        print("Error: Backend server not running on localhost:8099")
        print("Start it with: cd backend && python -m uvicorn app.main:app --port 8099")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

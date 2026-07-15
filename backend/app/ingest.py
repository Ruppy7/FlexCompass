"""Unified ingest runner — fetches from all portals and stores in SQLite.

Usage:
    python -m app.ingest              # ingest all
    python -m app.ingest --nged       # NGED only
    python -m app.ingest --spen       # SPEN only
    python -m app.ingest --enwl       # ENWL only
"""

from __future__ import annotations

import argparse
import time


def run_nged_ingest() -> dict[str, int]:
    """Run NGED ingest pipeline."""
    from .ingest_nged import (
        ingest_nged_dispatch,
        ingest_nged_postcodes,
        ingest_nged_procurement,
        ingest_nged_trade_results,
    )
    counts = {}
    print("[NGED] Starting ingest...")
    counts["postcodes"] = ingest_nged_postcodes()
    counts["procurement"] = ingest_nged_procurement(max_records=50000)
    counts["dispatch"] = ingest_nged_dispatch()
    counts["trade_results"] = ingest_nged_trade_results()
    return counts


def run_spen_ingest() -> dict[str, int]:
    """Run SPEN ingest pipeline."""
    from .ingest_spen import run_spen_ingest as _run
    return _run()


def run_enwl_ingest() -> dict[str, int]:
    """Run ENWL ingest pipeline."""
    from .ingest_enwl import run_enwl_ingest as _run
    return _run()


def run_ssen_ingest() -> dict[str, int]:
    """Run SSEN ingest pipeline."""
    from .ingest_ssen import run_ssen_ingest as _run
    return _run()


def run_all() -> dict[str, dict[str, int]]:
    """Run all ingest pipelines."""
    results = {}
    start = time.time()

    for name, fn in [("nged", run_nged_ingest), ("spen", run_spen_ingest),
                     ("enwl", run_enwl_ingest), ("ssen", run_ssen_ingest)]:
        t0 = time.time()
        try:
            results[name] = fn()
            elapsed = time.time() - t0
            total = sum(results[name].values())
            print(f"[{name.upper()}] Done: {total:,} records in {elapsed:.1f}s")
        except Exception as e:
            print(f"[{name.upper()}] FAILED: {e}")
            results[name] = {"error": str(e)}

    total_elapsed = time.time() - start
    print(f"\n[ALL] Total ingest time: {total_elapsed:.1f}s")
    for portal, counts in results.items():
        print(f"  {portal}: {counts}")
    return results


def main():
    parser = argparse.ArgumentParser(description="FlexCompass data ingest")
    parser.add_argument("--nged", action="store_true", help="Ingest NGED only")
    parser.add_argument("--spen", action="store_true", help="Ingest SPEN only")
    parser.add_argument("--enwl", action="store_true", help="Ingest ENWL only")
    args = parser.parse_args()

    if args.nged:
        run_nged_ingest()
    elif args.spen:
        run_spen_ingest()
    elif args.enwl:
        run_enwl_ingest()
    else:
        run_all()


if __name__ == "__main__":
    main()

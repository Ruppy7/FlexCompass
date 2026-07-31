"""Local-only command line entry point for public outage evidence sync."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from app.outage_source import sync_ssen_nafirs_hv


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.outage_cli",
        formatter_class=argparse.RawTextHelpFormatter,
        description=(
            "Synchronise public outage evidence into a local store; "
            "supported source: ssen-nafirs-hv."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    sync = commands.add_parser("sync", help="run a local read-only source sync")
    sync.add_argument("source", choices=("ssen-nafirs-hv",))
    sync.add_argument(
        "--db-path",
        type=Path,
        default=Path("data/cache/outages/registry.sqlite3"),
        help="local SQLite registry path",
    )
    sync.add_argument(
        "--snapshot-dir",
        type=Path,
        default=Path("data/snapshots/outages"),
        help="local content-addressed snapshot directory",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = sync_ssen_nafirs_hv(
        db_path=args.db_path,
        snapshot_dir=args.snapshot_dir,
    )
    print(
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    if result.status == "failed":
        return 1
    if result.rejects_written or result.warnings:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

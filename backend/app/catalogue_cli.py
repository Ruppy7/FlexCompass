"""Read-only command line interface for local public catalogue observations."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import httpx

from app.catalogue_models import CATALOGUE_PORTALS, CataloguePortalConfig
from app.catalogue_sync import diff_snapshots, redact, safe_error, summary_as_json, sync_catalogues

ROOT = Path(__file__).resolve().parents[2]


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage()
        self.exit(1, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    """Build a parser containing only local and read-only portal operations."""
    parser = _Parser(description="Synchronise and compare approved public catalogue metadata.")
    commands = parser.add_subparsers(dest="command", required=True)

    sync = commands.add_parser("sync", help="Fetch public metadata with anonymous read-only GET requests.")
    sync.add_argument("--portal", choices=("all", *CATALOGUE_PORTALS), default="all")
    sync.add_argument("--db-path", type=Path, default=ROOT / "data" / "cache" / "catalogue" / "registry.sqlite3")
    sync.add_argument("--output-dir", type=Path, default=ROOT / "data" / "snapshots" / "catalogues")
    sync.add_argument(
        "--review-queue-path",
        type=Path,
        default=ROOT / "data" / "cache" / "catalogue" / "review-queue.json",
    )
    sync.add_argument(
        "--policy-path",
        type=Path,
        default=ROOT / "data" / "catalogue" / "maintenance-policy.json",
    )

    diff = commands.add_parser("diff", help="Compare two local catalogue snapshots.")
    diff.add_argument("--before", type=Path, required=True)
    diff.add_argument("--after", type=Path, required=True)

    queue = commands.add_parser("review-queue", help="Print the local unresolved evidence queue.")
    queue.add_argument("--format", choices=("json",), default="json")
    queue.add_argument(
        "--path",
        type=Path,
        default=ROOT / "data" / "cache" / "catalogue" / "review-queue.json",
    )
    return parser


def _client_factory(portal: CataloguePortalConfig) -> httpx.Client:
    return httpx.Client(timeout=portal.timeout_seconds, follow_redirects=True)


def _print_json(value: object) -> None:
    print(json.dumps(redact(value), ensure_ascii=False, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    """Run a local command and return its documented process exit code."""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "sync":
            portals = list(CATALOGUE_PORTALS) if args.portal == "all" else [args.portal]
            summary = sync_catalogues(
                portals,
                _client_factory,
                args.db_path,
                args.output_dir,
                datetime.now(timezone.utc),
                review_queue_path=args.review_queue_path,
                policy_path=args.policy_path,
            )
            _print_json(summary_as_json(summary))
            return summary.exit_code
        if args.command == "diff":
            result = diff_snapshots(args.before, args.after)
            _print_json(
                {
                    "before": result.before.as_posix(),
                    "after": result.after.as_posix(),
                    "changes": [asdict(change) for change in result.changes],
                }
            )
            return 0
        queue = json.loads(args.path.read_text(encoding="utf-8")) if args.path.exists() else []
        _print_json(queue)
        return 0
    except Exception as error:
        _print_json({"status": "failed", "error": safe_error(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

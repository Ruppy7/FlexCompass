"""Safe local orchestration, snapshots, diffs, and review queues for catalogues."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.catalogue_adapters import CatalogueFetchResult, fetch_catalogue
from app.catalogue_classifier import DatasetAssessment, MaintenancePolicy, classify_dataset, load_policy
from app.catalogue_models import CATALOGUE_PORTALS, CatalogueDataset, CataloguePortalConfig, DatasetResource
from app.catalogue_store import persist_catalogue_assessment, persist_catalogue_result
from app.db import get_connection, run_migrations

ADAPTER_VERSION = "1"
SNAPSHOT_SCHEMA_VERSION = 1
SyncStatus = Literal["complete", "partial", "failed"]


@dataclass(frozen=True)
class PortalSyncOutcome:
    portal_id: str
    status: SyncStatus
    observed_at: datetime
    dataset_count: int = 0
    resource_count: int = 0
    complete: bool = False
    warnings: tuple[str, ...] = ()
    snapshot_path: Path | None = None
    content_hash: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class SyncRunSummary:
    status: SyncStatus
    portals: Mapping[str, PortalSyncOutcome]
    review_queue_path: Path

    @property
    def exit_code(self) -> int:
        return {"complete": 0, "partial": 2, "failed": 1}[self.status]

    @property
    def snapshot_paths(self) -> tuple[Path, ...]:
        return tuple(
            outcome.snapshot_path
            for outcome in self.portals.values()
            if outcome.snapshot_path is not None
        )


@dataclass(frozen=True)
class SnapshotChange:
    kind: str
    source_dataset_id: str
    before: Any = None
    after: Any = None


@dataclass(frozen=True)
class SnapshotDiff:
    before: Path
    after: Path
    changes: tuple[SnapshotChange, ...]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


_SENSITIVE_KEY = re.compile(
    r"(?:authorization|cookie|credential|password|secret|token|api[_-]?key)", re.IGNORECASE
)
_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_KEY_VALUE_SECRET = re.compile(
    r"(?i)(authorization|password|secret|token|api[_-]?key)\s*[=:]\s*[^\s,;&]+"
)


def _is_private_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    host = hostname.casefold().rstrip(".")
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not address.is_global


def _safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "[REDACTED_URL]"
    if parsed.username or parsed.password or _is_private_host(parsed.hostname):
        return "[REDACTED_URL]"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _safe_text(value: str) -> str:
    text = _KEY_VALUE_SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    return _URL.sub(lambda match: _safe_url(match.group(0)), text)


def safe_error(error: Exception) -> str:
    """Describe a failure without reflecting its potentially sensitive body."""
    return f"{type(error).__name__}: operation failed"


def redact(value: Any) -> Any:
    """Recursively remove authentication material and private endpoint details."""
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _safe_text(value)
    return value


def _snapshot_core(result: CatalogueFetchResult) -> dict[str, Any]:
    return redact(
        {
            "datasets": [dataset.model_dump(mode="json") for dataset in result.datasets],
            "resources": [resource.model_dump(mode="json") for resource in result.resources],
            "raw_pages": list(result.raw_pages),
        }
    )


def _without_observation_clock(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _without_observation_clock(item)
            for key, item in value.items()
            if key != "observed_at"
        }
    if isinstance(value, list):
        return [_without_observation_clock(item) for item in value]
    return value


def _redacted_result(result: CatalogueFetchResult, core: Mapping[str, Any]) -> CatalogueFetchResult:
    """Rebuild persistence contracts from the same redacted snapshot content."""
    return CatalogueFetchResult(
        portal_id=result.portal_id,
        observed_at=result.observed_at,
        datasets=[CatalogueDataset.model_validate(item) for item in core["datasets"]],
        resources=[DatasetResource.model_validate(item) for item in core["resources"]],
        expected_count=result.expected_count,
        complete=result.complete,
        warnings=tuple(redact(result.warnings)),
        raw_pages=tuple(core["raw_pages"]),
    )


def _timestamp_directory(now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    return now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _canonical_json(payload) + b"\n"
    if path.exists():
        if path.read_bytes() == encoded:
            return
        raise FileExistsError(f"immutable snapshot already exists: {path.name}")
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(encoded)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _classify(
    result: CatalogueFetchResult,
    policy: MaintenancePolicy,
    now: datetime,
) -> list[tuple[Any, DatasetAssessment]]:
    assessments: list[tuple[Any, DatasetAssessment]] = []
    for dataset in result.datasets:
        resources = [
            resource
            for resource in result.resources
            if resource.source_dataset_id == dataset.source_dataset_id
        ]
        assessment = classify_dataset(
            dataset,
            resources,
            dataset.classification_evidence,
            policy,
            now,
        )
        dataset.lifecycle_status = assessment.lifecycle
        dataset.publication_pattern = assessment.publication_pattern
        dataset.access_status = assessment.access_status
        assessments.append((dataset, assessment))
    return assessments


def _persist_assessments(
    conn: sqlite3.Connection,
    observation_id: str,
    assessments: Sequence[tuple[Any, DatasetAssessment]],
    now: datetime,
) -> None:
    for dataset, assessment in assessments:
        dimensions = (
            ("lifecycle", assessment.lifecycle, assessment.lifecycle_confidence, assessment.lifecycle_evidence),
            (
                "publication_pattern",
                assessment.publication_pattern,
                assessment.pattern_confidence,
                assessment.pattern_evidence,
            ),
            ("access", assessment.access_status, assessment.access_confidence, assessment.access_evidence),
            (
                "maintenance",
                assessment.maintenance_state,
                assessment.maintenance_confidence,
                assessment.maintenance_evidence,
            ),
        )
        for name, value, confidence, evidence in dimensions:
            unknown = getattr(value, "value", value) == "unknown"
            persist_catalogue_assessment(
                conn,
                assessment_id=f"{dataset.portal_id}:{dataset.source_dataset_id}:{name}",
                portal_id=dataset.portal_id,
                source_dataset_id=dataset.source_dataset_id,
                observation_id=observation_id,
                assessment_type=name,
                assessment_value=getattr(value, "value", value),
                confidence=confidence.value,
                rationale=[item.evidence for item in evidence]
                or (["Missing published evidence; no value was inferred."] if unknown else []),
                missing_evidence=[f"published evidence for {name}"] if unknown and not evidence else [],
                assessed_at=now,
            )


def _review_items(assessments: Sequence[tuple[Any, DatasetAssessment]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for dataset, assessment in assessments:
        dimensions = (
            ("lifecycle", assessment.lifecycle, assessment.lifecycle_evidence),
            ("publication_pattern", assessment.publication_pattern, assessment.pattern_evidence),
            ("access", assessment.access_status, assessment.access_evidence),
            ("maintenance", assessment.maintenance_state, assessment.maintenance_evidence),
        )
        for dimension, value, evidence in dimensions:
            if getattr(value, "value", value) != "unknown":
                continue
            reason = "conflict" if evidence else "missing_evidence"
            stable = f"{dataset.portal_id}\n{dataset.source_dataset_id}\n{dimension}\n{reason}"
            items.append(
                {
                    "id": hashlib.sha256(stable.encode()).hexdigest(),
                    "portal_id": dataset.portal_id,
                    "source_dataset_id": dataset.source_dataset_id,
                    "dimension": dimension,
                    "reason": reason,
                    "evidence_ids": sorted(item.id for item in evidence),
                }
            )
    return items


def _sync_one(
    portal_id: str,
    portal: CataloguePortalConfig,
    client_factory: Callable[[CataloguePortalConfig], httpx.Client],
    db_path: Path,
    output_dir: Path,
    now: datetime,
    fetcher: Callable[[CataloguePortalConfig, Any, datetime], CatalogueFetchResult],
    policy: MaintenancePolicy,
) -> tuple[PortalSyncOutcome, list[dict[str, Any]]]:
    client = client_factory(portal)
    try:
        result = fetcher(portal, client, now)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    if result.portal_id != portal_id:
        raise ValueError("adapter result portal does not match requested portal")
    assessments = _classify(result, policy, now)
    core = _snapshot_core(result)
    content_hash = hashlib.sha256(_canonical_json(_without_observation_clock(core))).hexdigest()
    snapshot_path = output_dir / _timestamp_directory(now) / f"{portal_id}.json"
    status: SyncStatus = "complete" if result.complete else "partial"
    manifest = {
        "adapter_version": ADAPTER_VERSION,
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "observed_at": now.astimezone(timezone.utc).isoformat(),
        "portal_id": portal_id,
        "portal_status": status,
        "dataset_count": len(result.datasets),
        "resource_count": len(result.resources),
        "expected_count": result.expected_count,
        "complete": result.complete,
        "warnings": redact(list(result.warnings)),
        "snapshot_path": snapshot_path.as_posix(),
        "content_hash": content_hash,
    }
    _write_json_atomic(snapshot_path, {"manifest": manifest, **core})
    with get_connection(db_path) as conn:
        persisted = persist_catalogue_result(
            conn,
            _redacted_result(result, core),
            snapshot_path.as_posix(),
            content_hash,
            status=status,
        )
        _persist_assessments(conn, persisted.observation_id, assessments, now)
    return (
        PortalSyncOutcome(
            portal_id=portal_id,
            status=status,
            observed_at=now,
            dataset_count=len(result.datasets),
            resource_count=len(result.resources),
            complete=result.complete,
            warnings=tuple(redact(result.warnings)),
            snapshot_path=snapshot_path,
            content_hash=content_hash,
        ),
        _review_items(assessments),
    )


def sync_catalogues(
    portal_ids: Sequence[str],
    client_factory: Callable[[CataloguePortalConfig], httpx.Client],
    db_path: Path,
    output_dir: Path,
    now: datetime,
    *,
    fetcher: Callable[[CataloguePortalConfig, Any, datetime], CatalogueFetchResult] = fetch_catalogue,
    review_queue_path: Path | None = None,
    policy_path: Path | None = None,
) -> SyncRunSummary:
    """Synchronise approved public catalogues independently using read-only adapters."""
    unknown = sorted(set(portal_ids) - set(CATALOGUE_PORTALS))
    if unknown:
        raise ValueError(f"unsupported catalogue portal: {', '.join(unknown)}")
    if not portal_ids:
        raise ValueError("at least one catalogue portal is required")
    root = Path(__file__).resolve().parents[2]
    policy = load_policy(policy_path or root / "data" / "catalogue" / "maintenance-policy.json")
    run_migrations(db_path)
    outcomes: dict[str, PortalSyncOutcome] = {}
    review_items: list[dict[str, Any]] = []
    for portal_id in portal_ids:
        try:
            outcome, items = _sync_one(
                portal_id,
                CATALOGUE_PORTALS[portal_id],
                client_factory,
                db_path,
                output_dir,
                now,
                fetcher,
                policy,
            )
            outcomes[portal_id] = outcome
            review_items.extend(items)
        except Exception as error:  # failures are isolated at the portal boundary
            outcomes[portal_id] = PortalSyncOutcome(
                portal_id=portal_id,
                status="failed",
                observed_at=now,
                error=safe_error(error),
            )
    statuses = {outcome.status for outcome in outcomes.values()}
    if statuses == {"complete"}:
        run_status: SyncStatus = "complete"
    elif statuses == {"failed"}:
        run_status = "failed"
    else:
        run_status = "partial"
    queue_path = review_queue_path or root / "data" / "cache" / "catalogue" / "review-queue.json"
    failed_portals = {
        portal_id for portal_id, outcome in outcomes.items() if outcome.status == "failed"
    }
    retained: list[dict[str, Any]] = []
    if queue_path.exists() and failed_portals:
        try:
            previous_queue = json.loads(queue_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_queue = []
        if isinstance(previous_queue, list):
            retained = [
                item
                for item in previous_queue
                if isinstance(item, dict) and item.get("portal_id") in failed_portals
            ]
    merged = {item["id"]: item for item in [*retained, *review_items]}
    _write_replaceable_json(queue_path, sorted(merged.values(), key=lambda item: item["id"]))
    return SyncRunSummary(run_status, outcomes, queue_path)


def _write_replaceable_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(_canonical_json(redact(payload)) + b"\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _dataset_map(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    datasets = payload.get("datasets", [])
    return {
        item["source_dataset_id"]: item
        for item in datasets
        if isinstance(item, Mapping) and isinstance(item.get("source_dataset_id"), str)
    }


def diff_snapshots(before: str | Path, after: str | Path) -> SnapshotDiff:
    """Return deterministic, evidence-only changes between two local snapshots."""
    before_path, after_path = Path(before), Path(after)
    before_data = json.loads(before_path.read_text(encoding="utf-8"))
    after_data = json.loads(after_path.read_text(encoding="utf-8"))
    old, new = _dataset_map(before_data), _dataset_map(after_data)
    changes: list[SnapshotChange] = []
    for source_id in sorted(new.keys() - old.keys()):
        changes.append(SnapshotChange("dataset_added", source_id, after=new[source_id]))
    for source_id in sorted(old.keys() - new.keys()):
        changes.append(SnapshotChange("dataset_removed", source_id, before=old[source_id]))
    metadata_fields = ("title", "description", "publisher", "licence", "portal_url", "api_url", "tags")
    for source_id in sorted(old.keys() & new.keys()):
        previous, current = old[source_id], new[source_id]
        before_metadata = {field: previous.get(field) for field in metadata_fields}
        after_metadata = {field: current.get(field) for field in metadata_fields}
        if before_metadata != after_metadata:
            changes.append(SnapshotChange("metadata_changed", source_id, before_metadata, after_metadata))
        if previous.get("resources", []) != current.get("resources", []):
            changes.append(
                SnapshotChange(
                    "resources_replaced",
                    source_id,
                    previous.get("resources", []),
                    current.get("resources", []),
                )
            )
        if previous.get("access_status") != current.get("access_status"):
            changes.append(
                SnapshotChange(
                    "access_changed",
                    source_id,
                    previous.get("access_status"),
                    current.get("access_status"),
                )
            )
    return SnapshotDiff(before_path, after_path, tuple(changes))


def summary_as_json(summary: SyncRunSummary) -> dict[str, Any]:
    """Return a public-safe JSON representation for CLI output."""
    return redact(
        {
            "status": summary.status,
            "exit_code": summary.exit_code,
            "review_queue_path": summary.review_queue_path.as_posix(),
            "portals": {
                portal_id: {
                    **asdict(outcome),
                    "observed_at": outcome.observed_at.isoformat(),
                    "snapshot_path": outcome.snapshot_path.as_posix() if outcome.snapshot_path else None,
                }
                for portal_id, outcome in summary.portals.items()
            },
        }
    )

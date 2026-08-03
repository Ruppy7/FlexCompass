"""Validation and immutable loading for catalogue snapshot schema version 1."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.catalogue_models import (
    CatalogueDataset,
    ClassificationEvidence,
    DatasetResource,
)
from app.catalogue_store import observation_key

SNAPSHOT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CatalogueSnapshot:
    """Validated immutable evidence reconstructed from one snapshot file."""

    portal_id: str
    observation_id: str
    observed_at: datetime
    content_hash: str
    datasets: tuple[CatalogueDataset, ...]
    resources: tuple[DatasetResource, ...]
    evidence: tuple[ClassificationEvidence, ...]


@dataclass(frozen=True)
class ValidatedSnapshotContent:
    """Validated JSON content used internally by sync and diff operations."""

    portal_id: str
    complete: bool
    manifest: Mapping[str, Any]
    datasets: Mapping[str, Mapping[str, Any]]
    collections: Mapping[str, list[Any]]


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def without_model_observation_clock(value: Mapping[str, Any]) -> dict[str, Any]:
    """Strip generated model clocks without changing source provenance."""
    cleaned = {key: item for key, item in value.items() if key != "observed_at"}
    for nested_field in ("resources", "classification_evidence"):
        nested = cleaned.get(nested_field)
        if isinstance(nested, list):
            cleaned[nested_field] = [
                without_model_observation_clock(item)
                if isinstance(item, Mapping)
                else item
                for item in nested
            ]
    return cleaned


_UNORDERED_SOURCE_LIST_KEYS = frozenset(
    {
        "attachments",
        "alternative_exports",
        "classification_evidence",
        "datasets",
        "groups",
        "resources",
        "results",
        "tags",
        "themes",
    }
)
_UNORDERED_IDENTITY_FIELDS = {
    "attachments": ("id", "url", "name", "title"),
    "alternative_exports": ("id", "url", "name", "title"),
    "classification_evidence": ("id",),
    "datasets": ("source_dataset_id", "id"),
    "groups": ("id", "name", "title"),
    "resources": ("id", "source_resource_id", "url", "name", "title"),
    "results": ("name", "id", "dataset_id", "dataset_uid"),
}


def _unordered_source_item_key(
    field_name: str | None,
    value: Any,
) -> tuple[str, bytes]:
    if isinstance(value, Mapping):
        for identity_field in _UNORDERED_IDENTITY_FIELDS.get(
            field_name or "", ()
        ):
            identity = value.get(identity_field)
            if isinstance(identity, str) and identity:
                return identity, canonical_json(value)
    return "", canonical_json(value)


def normalise_semantically_unordered(
    value: Any,
    field_name: str | None = None,
) -> Any:
    """Normalise known set-like source arrays without mutating provenance."""
    if isinstance(value, Mapping):
        return {
            key: normalise_semantically_unordered(item, str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        items = [normalise_semantically_unordered(item) for item in value]
        if field_name in _UNORDERED_SOURCE_LIST_KEYS:
            return sorted(
                items,
                key=lambda item: _unordered_source_item_key(field_name, item),
            )
        return items
    return value


def snapshot_identity(core: Mapping[str, Any]) -> dict[str, Any]:
    """Return snapshot hash input with generated model clocks removed."""
    identity = dict(core)
    for model_collection in ("datasets", "resources"):
        values = identity.get(model_collection)
        if isinstance(values, list):
            identity[model_collection] = [
                without_model_observation_clock(item)
                if isinstance(item, Mapping)
                else item
                for item in values
            ]
    normalised = normalise_semantically_unordered(identity)
    if not isinstance(normalised, dict):
        raise ValueError("snapshot identity must be a JSON object")
    return normalised


def comparable_resources(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    resources = [
        without_model_observation_clock(item)
        if isinstance(item, Mapping)
        else item
        for item in value
    ]
    return normalise_semantically_unordered(resources, "resources")


def _snapshot_portal(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        raise ValueError("snapshot must be a JSON object")
    manifest = payload.get("manifest")
    portal_id = manifest.get("portal_id") if isinstance(manifest, Mapping) else None
    if not isinstance(portal_id, str) or not portal_id:
        raise ValueError("snapshot manifest must contain portal_id")
    return portal_id


def _identity_key(value: Mapping[str, Any], *, kind: str) -> tuple[str, str, str]:
    portal_id = value.get("portal_id")
    source_dataset_id = value.get("source_dataset_id")
    identity = value.get("id")
    if not all(
        isinstance(item, str) and item
        for item in (portal_id, source_dataset_id, identity)
    ):
        raise ValueError(f"snapshot {kind} identity is invalid")
    return portal_id, source_dataset_id, identity


def validate_catalogue_snapshot_payload(payload: Any) -> ValidatedSnapshotContent:
    """Validate manifest, counts, associations, identities, and content hash."""
    portal_id = _snapshot_portal(payload)
    manifest = payload["manifest"]
    if manifest.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("unsupported snapshot schema version")
    status = manifest.get("portal_status")
    complete = manifest.get("complete")
    if status not in {"complete", "partial"} or not isinstance(complete, bool):
        raise ValueError("snapshot manifest has invalid completeness semantics")
    if complete != (status == "complete"):
        raise ValueError("snapshot manifest has inconsistent completeness semantics")

    collections: dict[str, list[Any]] = {}
    for field in ("datasets", "resources", "raw_pages"):
        value = payload.get(field)
        if not isinstance(value, list):
            raise ValueError(f"snapshot {field} must be a list")
        collections[field] = value
    datasets = collections["datasets"]
    resources = collections["resources"]
    if manifest.get("dataset_count") != len(datasets):
        raise ValueError("snapshot manifest dataset count is inconsistent")
    if manifest.get("resource_count") != len(resources):
        raise ValueError("snapshot manifest resource count is inconsistent")

    dataset_map: dict[str, Mapping[str, Any]] = {}
    nested_resources: list[Any] = []
    evidence_keys: set[tuple[str, str, str]] = set()
    nested_resource_keys: set[tuple[str, str, str]] = set()
    for dataset in datasets:
        if not isinstance(dataset, Mapping):
            raise ValueError("snapshot dataset must be a JSON object")
        source_id = dataset.get("source_dataset_id")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("snapshot dataset must contain source_dataset_id")
        if dataset.get("portal_id") != portal_id:
            raise ValueError("snapshot dataset portal association is invalid")
        if source_id in dataset_map:
            raise ValueError("snapshot dataset identifiers must be unique")
        dataset_map[source_id] = dataset

        dataset_resources = dataset.get("resources")
        if not isinstance(dataset_resources, list):
            raise ValueError("snapshot nested resources must be a list")
        for resource in dataset_resources:
            if not isinstance(resource, Mapping):
                raise ValueError("snapshot resource must be a JSON object")
            key = _identity_key(resource, kind="resource")
            if key[:2] != (portal_id, source_id):
                raise ValueError("snapshot resource association is invalid")
            if key in nested_resource_keys:
                raise ValueError("snapshot resource identity must be unique")
            nested_resource_keys.add(key)
            nested_resources.append(resource)

        evidence_items = dataset.get("classification_evidence")
        if not isinstance(evidence_items, list):
            raise ValueError("snapshot nested evidence must be a list")
        for evidence in evidence_items:
            if not isinstance(evidence, Mapping):
                raise ValueError("snapshot evidence must be a JSON object")
            key = _identity_key(evidence, kind="evidence")
            if key[:2] != (portal_id, source_id):
                raise ValueError("snapshot evidence association is invalid")
            if key in evidence_keys:
                raise ValueError("snapshot evidence identity must be unique")
            evidence_keys.add(key)

    resource_keys: set[tuple[str, str, str]] = set()
    for resource in resources:
        if not isinstance(resource, Mapping):
            raise ValueError("snapshot resource must be a JSON object")
        key = _identity_key(resource, kind="resource")
        if key[0] != portal_id or key[1] not in dataset_map:
            raise ValueError("snapshot resource association is invalid")
        if key in resource_keys:
            raise ValueError("snapshot resource identity must be unique")
        resource_keys.add(key)
    if nested_resource_keys != resource_keys or comparable_resources(
        nested_resources
    ) != comparable_resources(resources):
        raise ValueError("snapshot nested and top-level resources are inconsistent")

    expected_count = manifest.get("expected_count")
    if complete and (
        not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or expected_count < 0
        or len(dataset_map) != expected_count
    ):
        raise ValueError(
            "complete snapshot must match its expected unique usable dataset count"
        )

    core = {field: collections[field] for field in collections}
    expected_hash = hashlib.sha256(
        canonical_json(snapshot_identity(core))
    ).hexdigest()
    if manifest.get("content_hash") != expected_hash:
        raise ValueError("snapshot content hash does not match its source state")
    return ValidatedSnapshotContent(
        portal_id,
        complete,
        manifest,
        dataset_map,
        collections,
    )


def _manifest_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("snapshot manifest must contain observed_at")
    try:
        observed_at = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("snapshot manifest observed_at is invalid") from error
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("snapshot manifest observed_at must include a timezone")
    return observed_at.astimezone(timezone.utc)


def load_catalogue_snapshot(
    snapshot_path: Path,
    *,
    snapshot_root: Path,
    expected_portal_id: str,
    expected_content_hash: str,
) -> CatalogueSnapshot:
    """Resolve, validate, and reconstruct one immutable catalogue snapshot."""
    root = snapshot_root.resolve()
    try:
        candidate = snapshot_path.resolve(strict=True)
    except OSError as error:
        raise ValueError("catalogue snapshot is unavailable") from error
    if not candidate.is_relative_to(root):
        raise ValueError("catalogue snapshot path escapes snapshot root")
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("catalogue snapshot is unreadable") from error
    validated = validate_catalogue_snapshot_payload(payload)
    if not validated.complete:
        raise ValueError("catalogue snapshot is not complete")
    if validated.portal_id != expected_portal_id:
        raise ValueError("snapshot portal does not match observation")
    content_hash = validated.manifest.get("content_hash")
    if content_hash != expected_content_hash:
        raise ValueError("snapshot content hash does not match observation")
    observed_at = _manifest_timestamp(validated.manifest.get("observed_at"))

    datasets: list[CatalogueDataset] = []
    evidence: list[ClassificationEvidence] = []
    for value in validated.datasets.values():
        dataset = CatalogueDataset.model_validate(value)
        ordered_resources = sorted(
            dataset.resources,
            key=lambda item: (item.portal_id, item.source_dataset_id, item.id),
        )
        ordered_evidence = sorted(
            dataset.classification_evidence,
            key=lambda item: (item.portal_id, item.source_dataset_id, item.id),
        )
        datasets.append(
            dataset.model_copy(
                update={
                    "resources": ordered_resources,
                    "classification_evidence": ordered_evidence,
                }
            )
        )
        evidence.extend(ordered_evidence)
    ordered_datasets = tuple(
        sorted(
            datasets,
            key=lambda item: (item.portal_id, item.source_dataset_id, item.id),
        )
    )
    ordered_resources = tuple(
        sorted(
            (
                DatasetResource.model_validate(item)
                for item in validated.collections["resources"]
            ),
            key=lambda item: (item.portal_id, item.source_dataset_id, item.id),
        )
    )
    ordered_evidence = tuple(
        sorted(
            evidence,
            key=lambda item: (item.portal_id, item.source_dataset_id, item.id),
        )
    )
    return CatalogueSnapshot(
        portal_id=validated.portal_id,
        observation_id=observation_key(
            validated.portal_id,
            observed_at,
            content_hash,
        ),
        observed_at=observed_at,
        content_hash=content_hash,
        datasets=ordered_datasets,
        resources=ordered_resources,
        evidence=ordered_evidence,
    )

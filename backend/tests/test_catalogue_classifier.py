"""Behavioural tests for cadence-aware catalogue classification."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from app.catalogue_classifier import classify_dataset, load_policy
from app.catalogue_models import (
    AccessStatus,
    CatalogueDataset,
    ClassificationEvidence,
    DatasetResource,
    EvidenceConfidence,
    LifecycleStatus,
    MaintenanceState,
    PublicationPattern,
)

NOW = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)
POLICY_PATH = Path(__file__).parents[2] / "data" / "catalogue" / "maintenance-policy.json"


def _dataset(**overrides: Any) -> CatalogueDataset:
    values: dict[str, Any] = {
        "id": "portal:dataset-1",
        "portal_id": "portal",
        "source_dataset_id": "dataset-1",
        "title": "Public dataset",
        "description": None,
        "observed_at": NOW,
    }
    values.update(overrides)
    return CatalogueDataset(**values)


def _resource(updated_at: datetime | None) -> DatasetResource:
    return DatasetResource(
        id="portal:dataset-1:resource-1",
        portal_id="portal",
        source_dataset_id="dataset-1",
        source_updated_at=updated_at,
    )


def _evidence(
    classification: str,
    source_value: Any,
    *,
    confidence: EvidenceConfidence = EvidenceConfidence.high,
    evidence: str | None = None,
) -> ClassificationEvidence:
    return ClassificationEvidence(
        id=f"portal:dataset-1:{classification}",
        portal_id="portal",
        source_dataset_id="dataset-1",
        classification=classification,
        evidence=evidence or f"Explicit {classification} evidence",
        confidence=confidence,
        source_value=source_value,
        observed_at=NOW,
    )


@pytest.fixture
def policy():
    return load_policy(POLICY_PATH)


@pytest.mark.parametrize(
    ("frequency", "age_days", "expected"),
    [
        ("weekly", 6, MaintenanceState.on_schedule),
        ("weekly", 10, MaintenanceState.possibly_overdue),
        ("weekly", 16, MaintenanceState.stale),
        ("annually", 360, MaintenanceState.on_schedule),
    ],
)
def test_periodic_maintenance_uses_declared_cadence(
    policy, frequency: str, age_days: int, expected: MaintenanceState
) -> None:
    evidence = [
        _evidence("lifecycle_status", "active"),
        _evidence("portal_update_frequency", frequency),
    ]

    assessment = classify_dataset(
        _dataset(), [_resource(NOW - timedelta(days=age_days))], evidence, policy, NOW
    )

    assert assessment.lifecycle is LifecycleStatus.active
    assert assessment.publication_pattern is PublicationPattern.periodic
    assert assessment.maintenance_state is expected
    assert assessment.maintenance_confidence is EvidenceConfidence.high
    assert assessment.maintenance_evidence


@pytest.mark.parametrize(
    ("classification", "value", "lifecycle", "pattern"),
    [
        (
            "publication_pattern",
            "static_reference",
            LifecycleStatus.active,
            PublicationPattern.static_reference,
        ),
        (
            "publication_pattern",
            "closed_period",
            LifecycleStatus.historical_archive,
            PublicationPattern.closed_period,
        ),
        (
            "publication_pattern",
            "event_driven",
            LifecycleStatus.active,
            PublicationPattern.event_driven,
        ),
    ],
)
def test_description_supported_non_periodic_data_is_expected_dormant(
    policy,
    classification: str,
    value: str,
    lifecycle: LifecycleStatus,
    pattern: PublicationPattern,
) -> None:
    evidence = [
        _evidence("lifecycle_status", lifecycle.value),
        _evidence(
            classification,
            value,
            evidence=f"Dataset description explicitly identifies {value}",
        ),
    ]

    assessment = classify_dataset(
        _dataset(), [_resource(NOW - timedelta(days=900))], evidence, policy, NOW
    )

    assert assessment.lifecycle is lifecycle
    assert assessment.publication_pattern is pattern
    assert assessment.maintenance_state is MaintenanceState.expected_dormant


def test_description_supported_historical_archive_is_expected_dormant(policy) -> None:
    lifecycle_evidence = _evidence(
        "lifecycle_status",
        "historical_archive",
        evidence="Dataset description says this is a historical archive",
    )

    assessment = classify_dataset(
        _dataset(),
        [_resource(NOW - timedelta(days=900))],
        [lifecycle_evidence],
        policy,
        NOW,
    )

    assert assessment.lifecycle is LifecycleStatus.historical_archive
    assert assessment.maintenance_state is MaintenanceState.expected_dormant
    assert assessment.maintenance_evidence == (lifecycle_evidence,)


def test_restricted_access_cannot_force_current_data_stale(policy) -> None:
    evidence = [
        _evidence("lifecycle_status", "active"),
        _evidence("portal_update_frequency", "weekly"),
        _evidence("access_status", "restricted"),
    ]

    assessment = classify_dataset(
        _dataset(access_status=AccessStatus.restricted),
        [_resource(NOW - timedelta(days=2))],
        evidence,
        policy,
        NOW,
    )

    assert assessment.access_status is AccessStatus.restricted
    assert assessment.maintenance_state is MaintenanceState.on_schedule
    assert assessment.access_evidence
    assert assessment.access_confidence is EvidenceConfidence.high


def test_explicit_publisher_schedule_precedes_portal_frequency(policy) -> None:
    evidence = [
        _evidence("lifecycle_status", "active"),
        _evidence("publisher_schedule", {"frequency": "monthly"}),
        _evidence("portal_update_frequency", "weekly"),
    ]

    assessment = classify_dataset(
        _dataset(), [_resource(NOW - timedelta(days=20))], evidence, policy, NOW
    )

    assert assessment.maintenance_state is MaintenanceState.on_schedule
    assert "publisher_schedule" in assessment.maintenance_evidence[0].classification


def test_verified_timestamp_series_supplies_cadence_and_data_clock(policy) -> None:
    timestamps = [
        (NOW - timedelta(days=20)).isoformat(),
        (NOW - timedelta(days=13)).isoformat(),
        (NOW - timedelta(days=6)).isoformat(),
    ]
    evidence = [
        _evidence("lifecycle_status", "active"),
        _evidence("verified_timestamp_series", timestamps, confidence=EvidenceConfidence.medium),
    ]

    assessment = classify_dataset(
        _dataset(source_updated_at=NOW - timedelta(days=200)), [], evidence, policy, NOW
    )

    assert assessment.publication_pattern is PublicationPattern.periodic
    assert assessment.maintenance_state is MaintenanceState.on_schedule
    assert assessment.maintenance_confidence is EvidenceConfidence.medium


def test_catalogue_metadata_modification_is_not_used_as_the_data_clock(policy) -> None:
    evidence = [
        _evidence("lifecycle_status", "active"),
        _evidence("portal_update_frequency", "weekly"),
    ]

    assessment = classify_dataset(
        _dataset(source_updated_at=NOW),
        [_resource(NOW - timedelta(days=30))],
        evidence,
        policy,
        NOW,
    )

    assert assessment.maintenance_state is MaintenanceState.stale


def test_title_wording_alone_does_not_classify_dataset(policy) -> None:
    assessment = classify_dataset(
        _dataset(title="Old weekly archive static reference restricted"),
        [],
        [],
        policy,
        NOW,
    )

    assert assessment.lifecycle is LifecycleStatus.unknown
    assert assessment.publication_pattern is PublicationPattern.unknown
    assert assessment.access_status is AccessStatus.unknown
    assert assessment.maintenance_state is MaintenanceState.unknown


def test_wholly_unknown_evidence_returns_unknown_dimensions(policy) -> None:
    assessment = classify_dataset(_dataset(), [], [], policy, NOW)

    assert assessment.lifecycle is LifecycleStatus.unknown
    assert assessment.publication_pattern is PublicationPattern.unknown
    assert assessment.access_status is AccessStatus.unknown
    assert assessment.maintenance_state is MaintenanceState.unknown
    assert assessment.lifecycle_confidence is EvidenceConfidence.unknown
    assert assessment.pattern_confidence is EvidenceConfidence.unknown
    assert assessment.access_confidence is EvidenceConfidence.unknown
    assert assessment.maintenance_confidence is EvidenceConfidence.unknown
    assert assessment.lifecycle_evidence == ()
    assert assessment.pattern_evidence == ()
    assert assessment.access_evidence == ()
    assert assessment.maintenance_evidence == ()


def test_policy_is_versioned_generic_data_without_dataset_conclusions(policy) -> None:
    raw_policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    assert policy.schema_version == 1
    assert policy.publisher_frequencies["weekly"] == 7
    assert policy.grace_multipliers.possibly_overdue == 1.0
    assert policy.grace_multipliers.stale == 2.0
    assert policy.minimum_evidence_requirements
    assert "dataset" not in " ".join(raw_policy).lower()
    assert "overrides" not in raw_policy

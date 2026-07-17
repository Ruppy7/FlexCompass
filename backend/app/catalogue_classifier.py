"""Pure, evidence-led classification for public catalogue datasets."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

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


class GraceMultipliers(BaseModel):
    """Thresholds expressed as multiples of the expected cadence."""

    model_config = ConfigDict(frozen=True)

    possibly_overdue: float
    stale: float

    @field_validator("possibly_overdue", "stale")
    @classmethod
    def require_positive_multiplier(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("grace multipliers must be positive")
        return value

    @model_validator(mode="after")
    def require_ordered_thresholds(self) -> GraceMultipliers:
        if self.stale <= self.possibly_overdue:
            raise ValueError("stale multiplier must exceed possibly-overdue multiplier")
        return self


class MaintenancePolicy(BaseModel):
    """Versioned generic rules for cadence-based maintenance assessment."""

    model_config = ConfigDict(frozen=True)

    schema_version: int
    publisher_frequencies: Mapping[str, float]
    grace_multipliers: GraceMultipliers
    minimum_evidence_requirements: Mapping[str, int]

    @model_validator(mode="after")
    def validate_policy(self) -> MaintenancePolicy:
        if self.schema_version != 1:
            raise ValueError("unsupported maintenance policy schema version")
        if not self.publisher_frequencies:
            raise ValueError("publisher frequencies must not be empty")
        if any(days <= 0 for days in self.publisher_frequencies.values()):
            raise ValueError("publisher frequency intervals must be positive")
        if any(count <= 0 for count in self.minimum_evidence_requirements.values()):
            raise ValueError("minimum evidence requirements must be positive")
        return self


@dataclass(frozen=True)
class DatasetAssessment:
    """Independent dimensions and the evidence supporting each conclusion."""

    lifecycle: LifecycleStatus
    publication_pattern: PublicationPattern
    access_status: AccessStatus
    maintenance_state: MaintenanceState
    lifecycle_evidence: tuple[ClassificationEvidence, ...]
    lifecycle_confidence: EvidenceConfidence
    pattern_evidence: tuple[ClassificationEvidence, ...]
    pattern_confidence: EvidenceConfidence
    access_evidence: tuple[ClassificationEvidence, ...]
    access_confidence: EvidenceConfidence
    maintenance_evidence: tuple[ClassificationEvidence, ...]
    maintenance_confidence: EvidenceConfidence


@dataclass(frozen=True)
class _Dimension:
    value: Any
    evidence: tuple[ClassificationEvidence, ...] = ()
    confidence: EvidenceConfidence = EvidenceConfidence.unknown


@dataclass(frozen=True)
class _Cadence:
    days: float | None
    pattern: PublicationPattern
    evidence: tuple[ClassificationEvidence, ...]
    confidence: EvidenceConfidence
    latest_data_at: datetime | None = None


def load_policy(path: str | Path) -> MaintenancePolicy:
    """Load and validate a versioned maintenance policy from JSON."""

    with Path(path).open(encoding="utf-8") as policy_file:
        return MaintenancePolicy.model_validate(json.load(policy_file))


def classify_dataset(
    dataset: CatalogueDataset,
    resources: Sequence[DatasetResource],
    evidence: Sequence[ClassificationEvidence],
    policy: MaintenancePolicy,
    now: datetime,
) -> DatasetAssessment:
    """Classify one dataset deterministically from supplied public evidence."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")

    relevant = tuple(
        item
        for item in evidence
        if item.portal_id == dataset.portal_id
        and item.source_dataset_id == dataset.source_dataset_id
    )
    lifecycle = _classify_enum(
        relevant,
        ("lifecycle_status", "lifecycle"),
        LifecycleStatus,
        LifecycleStatus.unknown,
    )
    cadence = _select_cadence(relevant, policy)
    pattern = _classify_pattern(relevant, cadence, policy)
    access = _classify_enum(
        relevant,
        ("access_status", "access"),
        AccessStatus,
        AccessStatus.unknown,
    )
    maintenance = _classify_maintenance(
        dataset, resources, cadence, lifecycle, pattern, policy, now
    )

    return DatasetAssessment(
        lifecycle=lifecycle.value,
        publication_pattern=pattern.value,
        access_status=access.value,
        maintenance_state=maintenance.value,
        lifecycle_evidence=lifecycle.evidence,
        lifecycle_confidence=lifecycle.confidence,
        pattern_evidence=pattern.evidence,
        pattern_confidence=pattern.confidence,
        access_evidence=access.evidence,
        access_confidence=access.confidence,
        maintenance_evidence=maintenance.evidence,
        maintenance_confidence=maintenance.confidence,
    )


def _classify_enum(
    evidence: Sequence[ClassificationEvidence],
    classifications: tuple[str, ...],
    enum_type: type,
    unknown: Any,
    minimum_evidence: int = 1,
) -> _Dimension:
    for classification in classifications:
        accepted: list[tuple[Any, ClassificationEvidence]] = []
        for item in evidence:
            if item.classification != classification:
                continue
            try:
                value = enum_type(item.source_value)
            except (TypeError, ValueError):
                continue
            accepted.append((value, item))
        if not accepted:
            continue

        supporting_evidence = _ordered_evidence(item for _, item in accepted)
        values = {value for value, _ in accepted}
        if len(values) != 1 or len(supporting_evidence) < minimum_evidence:
            return _Dimension(unknown, supporting_evidence)
        return _Dimension(
            accepted[0][0],
            supporting_evidence,
            _lowest_confidence(supporting_evidence),
        )
    return _Dimension(unknown)


def _classify_pattern(
    evidence: Sequence[ClassificationEvidence],
    cadence: _Cadence,
    policy: MaintenancePolicy,
) -> _Dimension:
    if cadence.pattern is not PublicationPattern.unknown:
        return _Dimension(cadence.pattern, cadence.evidence, cadence.confidence)
    if cadence.evidence:
        return _Dimension(PublicationPattern.unknown, cadence.evidence)

    explicit = _classify_enum(
        evidence,
        ("publication_pattern", "pattern"),
        PublicationPattern,
        PublicationPattern.unknown,
    )
    if explicit.evidence:
        return explicit

    minimum = policy.minimum_evidence_requirements.get(
        "description_supported_state", 1
    )
    return _classify_enum(
        evidence,
        ("description_supported_state",),
        PublicationPattern,
        PublicationPattern.unknown,
        minimum,
    )


def _select_cadence(
    evidence: Sequence[ClassificationEvidence], policy: MaintenancePolicy
) -> _Cadence:
    for classification in ("publisher_schedule", "portal_update_frequency"):
        candidates: list[_Cadence] = []
        for item in evidence:
            if item.classification != classification:
                continue
            frequency = _frequency_value(item.source_value)
            if frequency in {"event_driven", "event-driven"}:
                candidates.append(
                    _Cadence(
                        None,
                        PublicationPattern.event_driven,
                        (item,),
                        item.confidence,
                    )
                )
                continue
            days = _cadence_days(item.source_value, frequency, policy)
            if days is not None:
                candidates.append(
                    _Cadence(
                        days,
                        PublicationPattern.periodic,
                        (item,),
                        item.confidence,
                    )
                )
        if candidates:
            return _resolve_cadence(candidates)

    minimum = policy.minimum_evidence_requirements.get("verified_timestamp_series", 3)
    candidates = []
    for item in evidence:
        if item.classification not in {
            "verified_timestamp_series",
            "timestamp_series",
        }:
            continue
        timestamps = _timestamp_values(item.source_value)
        if len(timestamps) < minimum:
            continue
        intervals = [
            (later - earlier).total_seconds() / 86400
            for earlier, later in zip(timestamps, timestamps[1:])
            if later > earlier
        ]
        if intervals:
            candidates.append(
                _Cadence(
                    median(intervals),
                    PublicationPattern.periodic,
                    (item,),
                    item.confidence,
                    timestamps[-1],
                )
            )
    if candidates:
        return _resolve_cadence(candidates)
    return _Cadence(
        None, PublicationPattern.unknown, (), EvidenceConfidence.unknown
    )


def _resolve_cadence(candidates: Sequence[_Cadence]) -> _Cadence:
    evidence = _ordered_evidence(
        item for candidate in candidates for item in candidate.evidence
    )
    values = {
        (candidate.days, candidate.pattern, candidate.latest_data_at)
        for candidate in candidates
    }
    if len(values) != 1:
        return _Cadence(
            None,
            PublicationPattern.unknown,
            evidence,
            EvidenceConfidence.unknown,
        )
    selected = candidates[0]
    return _Cadence(
        selected.days,
        selected.pattern,
        evidence,
        _lowest_confidence(evidence),
        selected.latest_data_at,
    )


def _lowest_confidence(
    evidence: Sequence[ClassificationEvidence],
) -> EvidenceConfidence:
    ranks = {
        EvidenceConfidence.unknown: 0,
        EvidenceConfidence.low: 1,
        EvidenceConfidence.medium: 2,
        EvidenceConfidence.high: 3,
    }
    return min((item.confidence for item in evidence), key=ranks.__getitem__)


def _ordered_evidence(
    evidence: Iterable[ClassificationEvidence],
) -> tuple[ClassificationEvidence, ...]:
    return tuple(
        sorted(
            evidence,
            key=lambda item: json.dumps(
                item.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
    )


def _frequency_value(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, Mapping):
        frequency = value.get("frequency")
        if isinstance(frequency, str):
            return frequency.strip().lower()
    return None


def _cadence_days(
    value: Any, frequency: str | None, policy: MaintenancePolicy
) -> float | None:
    if isinstance(value, Mapping):
        days = value.get("cadence_days")
        if isinstance(days, (int, float)) and not isinstance(days, bool) and days > 0:
            return float(days)
    if frequency is None:
        return None
    days = policy.publisher_frequencies.get(frequency)
    return float(days) if days is not None else None


def _timestamp_values(value: Any) -> list[datetime]:
    if not isinstance(value, list):
        return []
    timestamps: list[datetime] = []
    for raw_timestamp in value:
        if isinstance(raw_timestamp, datetime):
            timestamp = raw_timestamp
        elif isinstance(raw_timestamp, str):
            try:
                timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
            except ValueError:
                continue
        else:
            continue
        if timestamp.tzinfo is not None and timestamp.utcoffset() is not None:
            timestamps.append(timestamp)
    return sorted(set(timestamps))


def _classify_maintenance(
    dataset: CatalogueDataset,
    resources: Sequence[DatasetResource],
    cadence: _Cadence,
    lifecycle: _Dimension,
    pattern: _Dimension,
    policy: MaintenancePolicy,
    now: datetime,
) -> _Dimension:
    if lifecycle.value in {
        LifecycleStatus.historical_archive,
        LifecycleStatus.superseded,
        LifecycleStatus.retired,
    }:
        return _Dimension(
            MaintenanceState.expected_dormant,
            lifecycle.evidence,
            lifecycle.confidence,
        )
    if lifecycle.value is not LifecycleStatus.active:
        return _Dimension(MaintenanceState.unknown)
    if pattern.value in {
        PublicationPattern.event_driven,
        PublicationPattern.static_reference,
        PublicationPattern.closed_period,
    }:
        return _Dimension(
            MaintenanceState.expected_dormant,
            pattern.evidence,
            pattern.confidence,
        )
    if cadence.days is None:
        return _Dimension(MaintenanceState.unknown)

    latest_data_at = cadence.latest_data_at or _latest_resource_timestamp(
        dataset, resources
    )
    if latest_data_at is None:
        return _Dimension(MaintenanceState.unknown)
    age_days = max(0.0, (now - latest_data_at).total_seconds() / 86400)
    stale_after = cadence.days * policy.grace_multipliers.stale
    overdue_after = cadence.days * policy.grace_multipliers.possibly_overdue
    if age_days > stale_after:
        state = MaintenanceState.stale
    elif age_days > overdue_after:
        state = MaintenanceState.possibly_overdue
    else:
        state = MaintenanceState.on_schedule
    return _Dimension(state, cadence.evidence, cadence.confidence)


def _latest_resource_timestamp(
    dataset: CatalogueDataset,
    resources: Sequence[DatasetResource],
) -> datetime | None:
    timestamps = [
        resource.source_updated_at
        for resource in resources
        if resource.portal_id == dataset.portal_id
        and resource.source_dataset_id == dataset.source_dataset_id
        and resource.source_updated_at is not None
    ]
    return max(timestamps, default=None)

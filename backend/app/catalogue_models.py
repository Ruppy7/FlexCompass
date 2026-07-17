"""Canonical contracts for the public FlexCompass dataset catalogue."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PortalPlatform(str, Enum):
    ckan = "ckan"
    opendatasoft = "opendatasoft"


class LifecycleStatus(str, Enum):
    active = "active"
    historical_archive = "historical_archive"
    superseded = "superseded"
    retired = "retired"
    unknown = "unknown"


class PublicationPattern(str, Enum):
    continuous = "continuous"
    periodic = "periodic"
    event_driven = "event_driven"
    static_reference = "static_reference"
    closed_period = "closed_period"
    unknown = "unknown"


class MaintenanceState(str, Enum):
    on_schedule = "on_schedule"
    possibly_overdue = "possibly_overdue"
    stale = "stale"
    expected_dormant = "expected_dormant"
    unknown = "unknown"


class AccessStatus(str, Enum):
    public = "public"
    registered = "registered"
    restricted = "restricted"
    unreachable = "unreachable"
    unknown = "unknown"


class EvidenceConfidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"
    unknown = "unknown"


class CataloguePortalConfig(BaseModel):
    """Stable connection metadata for a public catalogue endpoint."""

    model_config = ConfigDict(frozen=True)

    operator_name: str
    platform: PortalPlatform
    portal_url: str
    api_base_url: str
    auth_env_var: str | None = None
    rate_limit_rps: float
    timeout_seconds: int
    max_pages: int


class _UtcTimestampModel(BaseModel):
    """Normalise timestamps to aware UTC datetimes at the contract boundary."""

    @field_validator(
        "observed_at",
        "source_created_at",
        "source_updated_at",
        check_fields=False,
    )
    @classmethod
    def normalise_timestamp_to_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(timezone.utc)


class ClassificationEvidence(_UtcTimestampModel):
    """Evidence supporting one non-factual catalogue classification."""

    id: str
    portal_id: str
    source_dataset_id: str
    classification: str
    evidence: str
    confidence: EvidenceConfidence = EvidenceConfidence.unknown
    source_value: Any | None = None
    source_url: str | None = None
    observed_at: datetime | None = None
    raw_record: dict[str, Any] = Field(default_factory=dict)


class DatasetResource(_UtcTimestampModel):
    """A resource belonging to one portal dataset, with raw provenance."""

    id: str
    portal_id: str
    source_dataset_id: str
    name: str | None = None
    description: str | None = None
    url: str | None = None
    format: str | None = None
    media_type: str | None = None
    size_bytes: int | None = None
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    observed_at: datetime | None = None
    raw_record: dict[str, Any] = Field(default_factory=dict)


class CatalogueDataset(_UtcTimestampModel):
    """Portal-normalised dataset metadata without inferred source facts."""

    id: str
    portal_id: str
    source_dataset_id: str
    title: str | None = None
    description: str | None = None
    publisher: str | None = None
    licence: str | None = None
    licence_identifier: str | None = None
    licence_title: str | None = None
    licence_url: str | None = None
    attribution: str | None = None
    themes: list[str] = Field(default_factory=list)
    catalogue_page_url: str | None = None
    metadata_api_url: str | None = None
    declared_update_frequency: str | None = None
    declared_update_frequency_text: str | None = None
    portal_url: str | None = None
    api_url: str | None = None
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    observed_at: datetime
    lifecycle_status: LifecycleStatus = LifecycleStatus.unknown
    publication_pattern: PublicationPattern = PublicationPattern.unknown
    access_status: AccessStatus = AccessStatus.unknown
    tags: list[str] = Field(default_factory=list)
    resources: list[DatasetResource] = Field(default_factory=list)
    classification_evidence: list[ClassificationEvidence] = Field(default_factory=list)
    raw_record: dict[str, Any] = Field(default_factory=dict)


class CatalogueObservation(_UtcTimestampModel):
    """A time-stamped public observation of a portal fetch."""

    id: str
    portal_id: str
    observed_at: datetime
    status: Literal["complete", "partial", "failed"]
    adapter_version: str | None = None
    schema_version: int | None = None
    content_hash: str | None = None
    expected_count: int | None = None
    dataset_count: int | None = None
    resource_count: int | None = None
    complete: bool | None = None
    snapshot_path: str | None = None
    request_class: str | None = None
    request_url: str | None = None
    endpoint: str | None = None
    response_status: int | None = None
    elapsed_seconds: float | None = None
    retry_count: int | None = None
    retry_outcome: str | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


CATALOGUE_PORTALS: Mapping[str, CataloguePortalConfig] = MappingProxyType(
    {
        "nged": CataloguePortalConfig(
            operator_name="National Grid Electricity Distribution",
            platform=PortalPlatform.ckan,
            portal_url="https://connecteddata.nationalgrid.co.uk/",
            api_base_url="https://connecteddata.nationalgrid.co.uk/api/3/action",
            auth_env_var="NGED_DATAPORTAL_TOKEN",
            rate_limit_rps=2.0,
            timeout_seconds=30,
            max_pages=1000,
        ),
        "spen": CataloguePortalConfig(
            operator_name="SP Energy Networks",
            platform=PortalPlatform.opendatasoft,
            portal_url="https://spenergynetworks.opendatasoft.com/",
            api_base_url="https://spenergynetworks.opendatasoft.com/api/explore/v2.1",
            auth_env_var="SPEN_DATAPORTAL_TOKEN",
            rate_limit_rps=2.0,
            timeout_seconds=30,
            max_pages=1000,
        ),
        "enwl": CataloguePortalConfig(
            operator_name="Electricity North West",
            platform=PortalPlatform.opendatasoft,
            portal_url="https://electricitynorthwest.opendatasoft.com/",
            api_base_url="https://electricitynorthwest.opendatasoft.com/api/explore/v2.1",
            auth_env_var="ENWL_DATAPORTAL_TOKEN",
            rate_limit_rps=2.0,
            timeout_seconds=30,
            max_pages=1000,
        ),
        "ssen": CataloguePortalConfig(
            operator_name="Scottish and Southern Electricity Networks",
            platform=PortalPlatform.ckan,
            portal_url="https://data.ssen.co.uk/",
            api_base_url="https://data-api.ssen.co.uk/api/3/action",
            auth_env_var="SSEN_DATAPORTAL_TOKEN",
            rate_limit_rps=1.0,
            timeout_seconds=30,
            max_pages=1000,
        ),
        "ukpn": CataloguePortalConfig(
            operator_name="UK Power Networks",
            platform=PortalPlatform.opendatasoft,
            portal_url="https://ukpowernetworks.opendatasoft.com/",
            api_base_url="https://ukpowernetworks.opendatasoft.com/api/explore/v2.1",
            auth_env_var="UKPN_DATAPORTAL_TOKEN",
            rate_limit_rps=2.0,
            timeout_seconds=30,
            max_pages=1000,
        ),
        "npg": CataloguePortalConfig(
            operator_name="Northern Powergrid",
            platform=PortalPlatform.opendatasoft,
            portal_url="https://northernpowergrid.opendatasoft.com/",
            api_base_url="https://northernpowergrid.opendatasoft.com/api/explore/v2.1",
            auth_env_var="NPG_DATAPORTAL_TOKEN",
            rate_limit_rps=2.0,
            timeout_seconds=30,
            max_pages=1000,
        ),
        "neso": CataloguePortalConfig(
            operator_name="National Energy System Operator",
            platform=PortalPlatform.ckan,
            portal_url="https://www.neso.energy/data-portal",
            api_base_url="https://api.neso.energy/api/3/action",
            auth_env_var="NESO_DATAPORTAL_TOKEN",
            rate_limit_rps=1.0,
            timeout_seconds=30,
            max_pages=1000,
        ),
    }
)

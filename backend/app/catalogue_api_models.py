"""Safe response projections for the public catalogue API."""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime
from typing import Generic, Literal, TypeVar
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field

from .catalogue_models import (
    AccessStatus,
    EvidenceConfidence,
    LifecycleStatus,
    PortalPlatform,
    PublicationPattern,
)

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class CataloguePortalSummaryV1(BaseModel):
    portal_id: str
    operator_name: str
    platform: PortalPlatform
    portal_url: str | None
    current_attempt_status: str | None
    current_attempt_at: datetime | None
    current_attempt_warning_count: int
    operational_review_window_hours: int = 168
    review_due_at: datetime | None
    review_status: Literal["current", "overdue", "never_attempted"]
    last_complete_observation_id: str | None
    last_complete_observed_at: datetime | None
    latest_complete_snapshot_valid: bool | None
    latest_complete_validation_state: Literal["valid", "invalid", "unavailable"]
    last_valid_observation_id: str | None
    last_valid_observed_at: datetime | None
    last_valid_dataset_count: int
    last_valid_resource_count: int
    degraded: bool
    snapshot_available: bool


class CatalogueDatasetPublicV1(BaseModel):
    dataset_ref: str
    portal_id: str
    source_dataset_id: str
    title: str | None
    description: str | None
    publisher: str | None
    licence: str | None
    licence_identifier: str | None
    licence_title: str | None
    licence_url: str | None
    attribution: str | None
    themes: list[str] = Field(default_factory=list)
    catalogue_page_url: str | None
    metadata_api_url: str | None
    declared_update_frequency: str | None
    declared_update_frequency_text: str | None
    portal_url: str | None
    api_url: str | None
    source_created_at: datetime | None
    source_updated_at: datetime | None
    observed_at: datetime
    lifecycle_status: LifecycleStatus
    publication_pattern: PublicationPattern
    access_status: AccessStatus
    tags: list[str] = Field(default_factory=list)


class CatalogueResourcePublicV1(BaseModel):
    id: str
    portal_id: str
    source_dataset_id: str
    name: str | None
    description: str | None
    url: str | None
    format: str | None
    media_type: str | None
    size_bytes: int | None
    source_created_at: datetime | None
    source_updated_at: datetime | None
    observed_at: datetime | None


class CatalogueEvidencePublicV1(BaseModel):
    id: str
    portal_id: str
    source_dataset_id: str
    classification: str
    evidence: str
    confidence: EvidenceConfidence
    source_url: str | None
    observed_at: datetime | None


class CatalogueAssessmentPublicV1(BaseModel):
    assessment_id: str
    observation_id: str
    assessment_type: str
    assessment_value: str
    confidence: str
    assessed_at: datetime


class CatalogueObservationPublicV1(BaseModel):
    observation_id: str
    portal_id: str
    observed_at: datetime | None
    status: Literal["complete", "partial", "failed"]
    adapter_version: str | None
    schema_version: int | None
    content_hash: str | None
    expected_count: int | None
    dataset_count: int | None
    resource_count: int | None
    complete: bool | None


def sanitise_public_url(value: str | None) -> str | None:
    """Strip query and fragment material from an otherwise public URL."""
    if value is None:
        return None
    if any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in value
    ):
        return None
    if "\\" in value:
        return None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or "%" in parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    canonical_host = hostname.rstrip(".").casefold()
    try:
        address = ipaddress.ip_address(canonical_host)
    except ValueError:
        numeric_part = r"(?:0[xX][0-9a-fA-F]+|\d+)"
        if re.fullmatch(rf"{numeric_part}(?:\.{numeric_part})*", canonical_host):
            return None
        if (
            "." not in canonical_host
            or canonical_host == "localhost"
            or canonical_host.endswith(
                (".localhost", ".local", ".internal", ".home", ".lan")
            )
        ):
            return None
    else:
        if not address.is_global:
            return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

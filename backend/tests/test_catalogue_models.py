"""Contract tests for the public catalogue registry models and portals."""

from datetime import datetime, timedelta, timezone

import pytest
from app.catalogue_models import (
    CATALOGUE_PORTALS,
    AccessStatus,
    CatalogueDataset,
    CatalogueObservation,
    ClassificationEvidence,
    DatasetResource,
    EvidenceConfidence,
    LifecycleStatus,
    MaintenanceState,
    PortalPlatform,
    PublicationPattern,
)
from app.config import config
from pydantic import ValidationError


def test_catalogue_portals_are_exactly_the_seven_approved_sources():
    assert set(CATALOGUE_PORTALS) == {
        "nged",
        "spen",
        "enwl",
        "ssen",
        "ukpn",
        "npg",
        "neso",
    }


def test_catalogue_portal_secrets_are_references_not_values():
    for portal in CATALOGUE_PORTALS.values():
        assert portal.auth_env_var is None or portal.auth_env_var.endswith("_TOKEN")
        assert "secret" not in portal.model_dump_json().casefold()


def test_catalogue_portals_use_verified_api_bases_and_platforms():
    expected = {
        "nged": ("https://connecteddata.nationalgrid.co.uk/api/3/action", PortalPlatform.ckan),
        "spen": (
            "https://spenergynetworks.opendatasoft.com/api/explore/v2.1",
            PortalPlatform.opendatasoft,
        ),
        "enwl": (
            "https://electricitynorthwest.opendatasoft.com/api/explore/v2.1",
            PortalPlatform.opendatasoft,
        ),
        "ssen": ("https://data-api.ssen.co.uk/api/3/action", PortalPlatform.ckan),
        "ukpn": (
            "https://ukpowernetworks.opendatasoft.com/api/explore/v2.1",
            PortalPlatform.opendatasoft,
        ),
        "npg": (
            "https://northernpowergrid.opendatasoft.com/api/explore/v2.1",
            PortalPlatform.opendatasoft,
        ),
        "neso": ("https://api.neso.energy/api/3/action", PortalPlatform.ckan),
    }

    assert {
        portal_id: (portal.api_base_url, portal.platform)
        for portal_id, portal in CATALOGUE_PORTALS.items()
    } == expected


def test_catalogue_portal_configuration_is_immutable():
    with pytest.raises(ValidationError):
        CATALOGUE_PORTALS["nged"].max_pages = 1


def test_legacy_portal_configuration_remains_available():
    assert config.portal("nged") is config.portals["nged"]


def test_canonical_classifications_default_to_unknown():
    dataset = CatalogueDataset(
        id="nged:example",
        portal_id="nged",
        source_dataset_id="example",
        observed_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )
    observation = CatalogueObservation(
        id="nged:example:2026-07-16T00:00:00Z",
        portal_id="nged",
        source_dataset_id="example",
        observed_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )
    evidence = ClassificationEvidence(
        classification="lifecycle_status",
        evidence="No current status was published by the source.",
    )

    assert dataset.lifecycle_status is LifecycleStatus.unknown
    assert dataset.publication_pattern is PublicationPattern.unknown
    assert dataset.access_status is AccessStatus.unknown
    assert observation.maintenance_state is MaintenanceState.unknown
    assert evidence.confidence is EvidenceConfidence.unknown


def test_catalogue_records_preserve_source_provenance_and_evidence():
    raw_record = {"id": "source-id", "source_only_field": True}
    resource = DatasetResource(
        id="nged:resource-id",
        source_dataset_id="source-id",
        raw_record=raw_record,
    )
    evidence = ClassificationEvidence(
        classification="access_status",
        evidence="The resource URL was returned by the public API.",
        confidence=EvidenceConfidence.high,
    )
    dataset = CatalogueDataset(
        id="nged:source-id",
        portal_id="nged",
        source_dataset_id="source-id",
        raw_record=raw_record,
        resources=[resource],
        classification_evidence=[evidence],
        observed_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )

    assert dataset.raw_record == raw_record
    assert dataset.resources[0].source_dataset_id == "source-id"
    assert dataset.classification_evidence == [evidence]
    assert dataset.title is None
    assert dataset.source_updated_at is None


def test_observation_timestamps_are_normalised_to_utc():
    observed_at = datetime(2026, 7, 16, 6, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    observation = CatalogueObservation(
        id="nged:example:observation",
        portal_id="nged",
        source_dataset_id="example",
        observed_at=observed_at,
    )

    assert observation.observed_at == datetime(2026, 7, 16, 1, 0, tzinfo=timezone.utc)
    assert observation.observed_at.tzinfo is timezone.utc


def test_observation_timestamps_reject_naive_datetimes():
    with pytest.raises(ValidationError):
        CatalogueObservation(
            id="nged:example:observation",
            portal_id="nged",
            source_dataset_id="example",
            observed_at=datetime(2026, 7, 16),
        )

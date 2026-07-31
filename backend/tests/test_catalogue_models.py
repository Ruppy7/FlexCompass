"""Contract tests for the public catalogue registry models and portals."""

from datetime import datetime, timedelta, timezone
from importlib.util import find_spec

import pytest
from app.catalogue_models import (
    CATALOGUE_PORTAL_IDS,
    CATALOGUE_PORTALS,
    AccessStatus,
    CatalogueDataset,
    CatalogueObservation,
    ClassificationEvidence,
    DatasetResource,
    EvidenceConfidence,
    LifecycleStatus,
    PortalPlatform,
    PublicationPattern,
)
from app.config import config
from pydantic import ValidationError


def test_canonical_portal_ids_match_exact_configuration() -> None:
    assert CATALOGUE_PORTAL_IDS == (
        "nged",
        "spen",
        "enwl",
        "ssen",
        "ukpn",
        "npg",
        "neso",
    )
    assert tuple(CATALOGUE_PORTALS) == CATALOGUE_PORTAL_IDS


def test_application_config_has_no_duplicate_portal_registry() -> None:
    assert not hasattr(config, "portals")
    assert not hasattr(config, "portal")


def test_unverified_catalogue_fetcher_is_retired() -> None:
    assert find_spec("app.portal_fetcher") is None


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

    with pytest.raises(TypeError):
        CATALOGUE_PORTALS["new"] = CATALOGUE_PORTALS["nged"]

    with pytest.raises(TypeError):
        CATALOGUE_PORTALS["nged"] = CATALOGUE_PORTALS["spen"]


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
        observed_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
        status="complete",
    )
    evidence = ClassificationEvidence(
        id="nged:example:lifecycle-status",
        portal_id="nged",
        source_dataset_id="example",
        classification="lifecycle_status",
        evidence="No current status was published by the source.",
    )

    assert dataset.lifecycle_status is LifecycleStatus.unknown
    assert dataset.publication_pattern is PublicationPattern.unknown
    assert dataset.access_status is AccessStatus.unknown
    assert observation.status == "complete"
    assert evidence.confidence is EvidenceConfidence.unknown


def test_catalogue_records_preserve_source_provenance_and_evidence():
    raw_record = {"id": "source-id", "source_only_field": True}
    resource = DatasetResource(
        id="nged:resource-id",
        portal_id="nged",
        source_dataset_id="source-id",
        raw_record=raw_record,
    )
    evidence = ClassificationEvidence(
        id="nged:source-id:access-status",
        portal_id="nged",
        source_dataset_id="source-id",
        classification="access_status",
        evidence="The resource URL was returned by the public API.",
        confidence=EvidenceConfidence.high,
        raw_record=raw_record,
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
    assert dataset.resources[0].id == "nged:resource-id"
    assert dataset.resources[0].portal_id == "nged"
    assert dataset.resources[0].source_dataset_id == "source-id"
    assert dataset.resources[0].raw_record == raw_record
    assert dataset.classification_evidence[0].id == "nged:source-id:access-status"
    assert dataset.classification_evidence[0].portal_id == "nged"
    assert dataset.classification_evidence[0].source_dataset_id == "source-id"
    assert dataset.classification_evidence[0].raw_record == raw_record
    assert dataset.classification_evidence == [evidence]
    assert dataset.title is None
    assert dataset.source_updated_at is None


@pytest.mark.parametrize(
    ("record_type", "values", "missing_field"),
    [
        (
            DatasetResource,
            {
                "id": "nged:resource-id",
                "portal_id": "nged",
                "source_dataset_id": "source-id",
            },
            "portal_id",
        ),
        (
            ClassificationEvidence,
            {
                "id": "nged:source-id:access-status",
                "portal_id": "nged",
                "source_dataset_id": "source-id",
                "classification": "access_status",
                "evidence": "Published by the public source.",
            },
            "id",
        ),
        (
            ClassificationEvidence,
            {
                "id": "nged:source-id:access-status",
                "portal_id": "nged",
                "source_dataset_id": "source-id",
                "classification": "access_status",
                "evidence": "Published by the public source.",
            },
            "portal_id",
        ),
        (
            ClassificationEvidence,
            {
                "id": "nged:source-id:access-status",
                "portal_id": "nged",
                "source_dataset_id": "source-id",
                "classification": "access_status",
                "evidence": "Published by the public source.",
            },
            "source_dataset_id",
        ),
    ],
)
def test_nested_catalogue_provenance_fields_are_required(
    record_type, values, missing_field
):
    values.pop(missing_field)

    with pytest.raises(ValidationError):
        record_type(**values)


def test_observation_timestamps_are_normalised_to_utc():
    observed_at = datetime(2026, 7, 16, 6, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    observation = CatalogueObservation(
        id="nged:example:observation",
        portal_id="nged",
        observed_at=observed_at,
        status="complete",
    )

    assert observation.observed_at == datetime(2026, 7, 16, 1, 0, tzinfo=timezone.utc)
    assert observation.observed_at.tzinfo is timezone.utc


def test_observation_timestamps_reject_naive_datetimes():
    with pytest.raises(ValidationError):
        CatalogueObservation(
            id="nged:example:observation",
            portal_id="nged",
            observed_at=datetime(2026, 7, 16),
            status="complete",
        )


def test_s8_observation_contract_has_store_aligned_fields():
    """S8: CatalogueObservation has status, content_hash, completeness, and nullable request facts."""
    observation = CatalogueObservation(
        id="nged:example:observation",
        portal_id="nged",
        observed_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
        status="complete",
    )
    # Store-aligned fields with defaults
    assert observation.status == "complete"
    assert observation.complete is None
    assert observation.content_hash is None
    assert observation.expected_count is None
    assert observation.dataset_count is None
    assert observation.resource_count is None
    assert observation.snapshot_path is None
    assert observation.adapter_version is None
    assert observation.schema_version is None
    assert observation.request_class is None
    # Nullable request/endpoint/response/elapsed/retry facts
    assert observation.request_url is None
    assert observation.endpoint is None
    assert observation.response_status is None
    assert observation.elapsed_seconds is None
    assert observation.retry_count is None
    assert observation.retry_outcome is None
    assert observation.errors == []
    assert observation.warnings == []


def test_s8_observation_status_is_required_and_completeness_is_not_inferred():
    """S8: Missing fetch status is invalid while unknown completeness stays null."""
    with pytest.raises(ValidationError, match="status"):
        CatalogueObservation(
            id="nged:observation",
            portal_id="nged",
            observed_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
        )

    with pytest.raises(ValidationError, match="status"):
        CatalogueObservation(
            id="nged:observation",
            portal_id="nged",
            observed_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
            status="guessed",
        )


def test_s9_dataset_canonical_metadata_defaults_to_none():
    """S9: New canonical metadata fields default to None/empty."""
    dataset = CatalogueDataset(
        id="nged:example",
        portal_id="nged",
        source_dataset_id="example",
        observed_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )
    assert dataset.licence_identifier is None
    assert dataset.licence_title is None
    assert dataset.licence_url is None
    assert dataset.attribution is None
    assert dataset.themes == []
    assert dataset.catalogue_page_url is None
    assert dataset.metadata_api_url is None
    assert dataset.declared_update_frequency is None
    assert dataset.declared_update_frequency_text is None

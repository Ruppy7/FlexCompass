"""Versioned GET-only public catalogue routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from .catalogue_api_models import (
    CatalogueAssessmentPublicV1,
    CatalogueDatasetPublicV1,
    CatalogueEvidencePublicV1,
    CatalogueObservationPublicV1,
    CataloguePortalSummaryV1,
    CatalogueResourcePublicV1,
    Page,
    sanitise_public_url,
)
from .catalogue_identity import decode_dataset_ref, encode_dataset_ref
from .catalogue_models import (
    CATALOGUE_PORTAL_IDS,
    CATALOGUE_PORTALS,
    AccessStatus,
    CatalogueDataset,
    ClassificationEvidence,
    DatasetResource,
    LifecycleStatus,
    PortalId,
    PublicationPattern,
)
from .catalogue_repository import CatalogueRepository, PortalState
from .config import FlexCompassConfig

router = APIRouter(prefix="/api/v1/catalogue")
CATALOGUE_REVIEW_WINDOW_HOURS = 168


def _settings(request: Request) -> FlexCompassConfig:
    return request.app.state.settings


def _repository(request: Request) -> CatalogueRepository:
    settings = _settings(request)
    return CatalogueRepository(
        db_path=settings.catalogue_db_path,
        snapshot_root=settings.catalogue_snapshot_dir,
    )


def _portal_summary(
    portal_id: PortalId,
    state: PortalState,
) -> CataloguePortalSummaryV1:
    public_config = CATALOGUE_PORTALS[portal_id]
    return CataloguePortalSummaryV1(
        portal_id=portal_id,
        operator_name=public_config.operator_name,
        platform=public_config.platform,
        portal_url=sanitise_public_url(public_config.portal_url),
        current_attempt_status=state.current_attempt_status,
        current_attempt_at=state.current_attempt_at,
        current_attempt_warning_count=state.current_attempt_warning_count,
        operational_review_window_hours=CATALOGUE_REVIEW_WINDOW_HOURS,
        review_due_at=state.review_due_at,
        review_status=state.review_status,
        last_complete_observation_id=state.last_complete_observation_id,
        last_complete_observed_at=state.last_complete_observed_at,
        latest_complete_snapshot_valid=state.latest_complete_snapshot_valid,
        latest_complete_validation_state=state.latest_complete_validation_state,
        last_valid_observation_id=state.last_valid_observation_id,
        last_valid_observed_at=state.last_valid_observed_at,
        last_valid_dataset_count=state.last_valid_dataset_count,
        last_valid_resource_count=state.last_valid_resource_count,
        degraded=state.degraded,
        snapshot_available=state.snapshot_available,
    )


def _dataset_projection(dataset: CatalogueDataset) -> CatalogueDatasetPublicV1:
    return CatalogueDatasetPublicV1(
        dataset_ref=encode_dataset_ref(dataset.portal_id, dataset.source_dataset_id),
        portal_id=dataset.portal_id,
        source_dataset_id=dataset.source_dataset_id,
        title=dataset.title,
        description=dataset.description,
        publisher=dataset.publisher,
        licence=dataset.licence,
        licence_identifier=dataset.licence_identifier,
        licence_title=dataset.licence_title,
        licence_url=sanitise_public_url(dataset.licence_url),
        attribution=dataset.attribution,
        themes=dataset.themes,
        catalogue_page_url=sanitise_public_url(dataset.catalogue_page_url),
        metadata_api_url=sanitise_public_url(dataset.metadata_api_url),
        declared_update_frequency=dataset.declared_update_frequency,
        declared_update_frequency_text=dataset.declared_update_frequency_text,
        portal_url=sanitise_public_url(dataset.portal_url),
        api_url=sanitise_public_url(dataset.api_url),
        source_created_at=dataset.source_created_at,
        source_updated_at=dataset.source_updated_at,
        observed_at=dataset.observed_at,
        lifecycle_status=dataset.lifecycle_status,
        publication_pattern=dataset.publication_pattern,
        access_status=dataset.access_status,
        tags=dataset.tags,
    )


def _resource_projection(resource: DatasetResource) -> CatalogueResourcePublicV1:
    return CatalogueResourcePublicV1(
        id=resource.id,
        portal_id=resource.portal_id,
        source_dataset_id=resource.source_dataset_id,
        name=resource.name,
        description=resource.description,
        url=sanitise_public_url(resource.url),
        format=resource.format,
        media_type=resource.media_type,
        size_bytes=resource.size_bytes,
        source_created_at=resource.source_created_at,
        source_updated_at=resource.source_updated_at,
        observed_at=resource.observed_at,
    )


def _evidence_projection(
    evidence: ClassificationEvidence,
) -> CatalogueEvidencePublicV1:
    return CatalogueEvidencePublicV1(
        id=evidence.id,
        portal_id=evidence.portal_id,
        source_dataset_id=evidence.source_dataset_id,
        classification=evidence.classification,
        evidence=evidence.evidence,
        confidence=evidence.confidence,
        source_url=sanitise_public_url(evidence.source_url),
        observed_at=evidence.observed_at,
    )


def _decode_ref(value: str) -> tuple[PortalId, str]:
    try:
        portal_id, source_dataset_id = decode_dataset_ref(value)
    except ValueError as exc:
        raise HTTPException(status_code=422) from exc
    return portal_id, source_dataset_id  # type: ignore[return-value]


def _page(items: list[object], *, total: int, limit: int, offset: int) -> dict[str, object]:
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/portals", response_model=Page[CataloguePortalSummaryV1])
def list_catalogue_portals(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    repository = _repository(request)
    now = datetime.now(timezone.utc)
    items = [
        _portal_summary(portal_id, repository.portal_state(portal_id, now=now))
        for portal_id in CATALOGUE_PORTAL_IDS
    ]
    return _page(items[offset : offset + limit], total=len(items), limit=limit, offset=offset)


@router.get("/portals/{portal_id}", response_model=CataloguePortalSummaryV1)
def get_catalogue_portal(portal_id: str, request: Request) -> CataloguePortalSummaryV1:
    if portal_id not in CATALOGUE_PORTAL_IDS:
        raise HTTPException(status_code=404)
    typed_portal: PortalId = portal_id  # type: ignore[assignment]
    repository = _repository(request)
    return _portal_summary(
        typed_portal,
        repository.portal_state(typed_portal, now=datetime.now(timezone.utc)),
    )


def _maintenance_matches(
    repository: CatalogueRepository,
    dataset: CatalogueDataset,
    maintenance_state: str,
) -> bool:
    return any(
        row.get("assessment_type") == "maintenance"
        and row.get("assessment_value") == maintenance_state
        for row in repository.list_last_valid_assessments(
            dataset.portal_id, dataset.source_dataset_id
        )
    )


@router.get("/datasets", response_model=Page[CatalogueDatasetPublicV1])
def list_catalogue_datasets(
    request: Request,
    portal_id: Annotated[PortalId | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=1)] = None,
    lifecycle_status: Annotated[LifecycleStatus | None, Query()] = None,
    publication_pattern: Annotated[PublicationPattern | None, Query()] = None,
    access_status: Annotated[AccessStatus | None, Query()] = None,
    maintenance_state: Annotated[str | None, Query(min_length=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    repository = _repository(request)
    portal_ids = (portal_id,) if portal_id is not None else CATALOGUE_PORTAL_IDS
    datasets = [
        dataset
        for selected_portal in portal_ids
        for dataset in repository.list_last_valid_datasets(selected_portal)
    ]
    if q is not None:
        needle = q.casefold()
        datasets = [
            item
            for item in datasets
            if needle
            in " ".join(
                filter(
                    None,
                    (item.source_dataset_id, item.title, item.description, item.publisher),
                )
            ).casefold()
        ]
    if lifecycle_status is not None:
        datasets = [item for item in datasets if item.lifecycle_status == lifecycle_status]
    if publication_pattern is not None:
        datasets = [
            item for item in datasets if item.publication_pattern == publication_pattern
        ]
    if access_status is not None:
        datasets = [item for item in datasets if item.access_status == access_status]
    if maintenance_state is not None:
        datasets = [
            item
            for item in datasets
            if _maintenance_matches(repository, item, maintenance_state)
        ]
    datasets.sort(key=lambda item: (item.portal_id, item.source_dataset_id))
    items = [_dataset_projection(item) for item in datasets]
    return _page(items[offset : offset + limit], total=len(items), limit=limit, offset=offset)


def _require_dataset(
    repository: CatalogueRepository,
    dataset_ref: str,
) -> tuple[PortalId, str, CatalogueDataset]:
    portal_id, source_dataset_id = _decode_ref(dataset_ref)
    dataset = repository.get_last_valid_dataset(portal_id, source_dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404)
    return portal_id, source_dataset_id, dataset


@router.get("/datasets/{dataset_ref}", response_model=CatalogueDatasetPublicV1)
def get_catalogue_dataset(
    dataset_ref: str, request: Request
) -> CatalogueDatasetPublicV1:
    _, _, dataset = _require_dataset(_repository(request), dataset_ref)
    return _dataset_projection(dataset)


@router.get(
    "/datasets/{dataset_ref}/resources",
    response_model=Page[CatalogueResourcePublicV1],
)
def list_catalogue_resources(
    dataset_ref: str,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    repository = _repository(request)
    portal_id, source_dataset_id, _ = _require_dataset(repository, dataset_ref)
    resources = sorted(
        repository.list_last_valid_resources(portal_id, source_dataset_id),
        key=lambda item: item.id,
    )
    items = [_resource_projection(item) for item in resources]
    return _page(items[offset : offset + limit], total=len(items), limit=limit, offset=offset)


@router.get(
    "/datasets/{dataset_ref}/evidence",
    response_model=Page[CatalogueEvidencePublicV1],
)
def list_catalogue_evidence(
    dataset_ref: str,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    repository = _repository(request)
    portal_id, source_dataset_id, _ = _require_dataset(repository, dataset_ref)
    evidence = sorted(
        repository.list_last_valid_evidence(portal_id, source_dataset_id),
        key=lambda item: item.id,
    )
    items = [_evidence_projection(item) for item in evidence]
    return _page(items[offset : offset + limit], total=len(items), limit=limit, offset=offset)


@router.get(
    "/datasets/{dataset_ref}/assessments",
    response_model=Page[CatalogueAssessmentPublicV1],
)
def list_catalogue_assessments(
    dataset_ref: str,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    repository = _repository(request)
    portal_id, source_dataset_id, _ = _require_dataset(repository, dataset_ref)
    rows = sorted(
        repository.list_last_valid_assessments(portal_id, source_dataset_id),
        key=lambda item: (str(item["assessment_type"]), str(item["assessment_id"])),
    )
    items = [CatalogueAssessmentPublicV1.model_validate(row) for row in rows]
    return _page(items[offset : offset + limit], total=len(items), limit=limit, offset=offset)


@router.get("/observations", response_model=Page[CatalogueObservationPublicV1])
def list_catalogue_observations(
    request: Request,
    portal_id: Annotated[PortalId | None, Query()] = None,
    status: Annotated[str | None, Query(pattern="^(complete|partial|failed)$")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    repository = _repository(request)
    records = list(repository.list_observations(portal_id))
    if status is not None:
        records = [item for item in records if item.status == status]
    items = [CatalogueObservationPublicV1.model_validate(item.__dict__) for item in records]
    return _page(items[offset : offset + limit], total=len(items), limit=limit, offset=offset)

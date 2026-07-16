"""Read-only adapters for supported public dataset catalogues."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

import httpx

from app.catalogue_models import (
    CATALOGUE_PORTALS,
    CatalogueDataset,
    CataloguePortalConfig,
    DatasetResource,
    PortalPlatform,
)

PAGE_SIZE = 1


@dataclass(frozen=True)
class CatalogueFetchResult:
    portal_id: str
    observed_at: datetime
    datasets: Sequence[CatalogueDataset]
    resources: Sequence[DatasetResource]
    expected_count: int | None
    complete: bool
    warnings: Sequence[str]
    raw_pages: Sequence[dict[str, Any]]


def fetch_catalogue(
    portal: CataloguePortalConfig,
    client: httpx.Client,
    observed_at: datetime,
) -> CatalogueFetchResult:
    if portal.platform is PortalPlatform.ckan:
        return fetch_ckan_catalogue(portal, client, observed_at)
    if portal.platform is PortalPlatform.opendatasoft:
        return fetch_ods_catalogue(portal, client, observed_at)
    raise ValueError(f"Unsupported catalogue platform: {portal.platform}")


def fetch_ckan_catalogue(
    portal: CataloguePortalConfig,
    client: httpx.Client,
    observed_at: datetime,
) -> CatalogueFetchResult:
    portal_id = _portal_id(portal)
    url = f"{portal.api_base_url.rstrip('/')}/package_search"
    pages: list[dict[str, Any]] = []
    datasets: list[CatalogueDataset] = []
    resources: list[DatasetResource] = []
    warnings: list[str] = []
    expected_count: int | None = None
    seen_pages: set[tuple[str, ...]] = set()

    for page_number in range(portal.max_pages):
        start = page_number * PAGE_SIZE
        response = client.get(url, params={"rows": PAGE_SIZE, "start": start})
        response.raise_for_status()
        page = response.json()
        pages.append(page)
        result = page.get("result") if isinstance(page, dict) else None
        result = result if isinstance(result, dict) else {}
        if page_number == 0:
            expected_count = _optional_nonnegative_int(result.get("count"))
            if expected_count is None:
                warnings.append("Pagination total count is absent; completeness is unknown.")

        records = result.get("results")
        records = records if isinstance(records, list) else []
        if not records:
            if expected_count is not None and len(datasets) < expected_count:
                warnings.append("Pagination ended on an empty page before the reported count.")
            break

        page_key = tuple(_source_id(record, "name", "id") for record in records)
        if page_key in seen_pages:
            warnings.append("Pagination returned a repeated page before completion.")
            break
        seen_pages.add(page_key)

        for record in records:
            dataset, dataset_resources = _map_ckan_dataset(portal_id, record, observed_at)
            datasets.append(dataset)
            resources.extend(dataset_resources)

        if expected_count is None or len(datasets) >= expected_count:
            break
    else:
        warnings.append("Pagination reached max_pages before completion.")

    complete = expected_count is not None and len(datasets) >= expected_count
    if not complete and len(pages) >= portal.max_pages and not any("max_pages" in warning for warning in warnings):
        warnings.append("Pagination reached max_pages before completion.")
    return CatalogueFetchResult(
        portal_id=portal_id,
        observed_at=observed_at,
        datasets=datasets,
        resources=resources,
        expected_count=expected_count,
        complete=complete,
        warnings=warnings,
        raw_pages=pages,
    )


def fetch_ods_catalogue(
    portal: CataloguePortalConfig,
    client: httpx.Client,
    observed_at: datetime,
) -> CatalogueFetchResult:
    portal_id = _portal_id(portal)
    url = f"{portal.api_base_url.rstrip('/')}/catalog/datasets"
    pages: list[dict[str, Any]] = []
    datasets: list[CatalogueDataset] = []
    resources: list[DatasetResource] = []
    warnings: list[str] = []
    expected_count: int | None = None
    seen_pages: set[tuple[str, ...]] = set()

    for page_number in range(portal.max_pages):
        offset = page_number * PAGE_SIZE
        response = client.get(url, params={"limit": PAGE_SIZE, "offset": offset})
        response.raise_for_status()
        page = response.json()
        pages.append(page)
        if page_number == 0:
            expected_count = _optional_nonnegative_int(page.get("total_count"))
            if expected_count is None:
                warnings.append("Pagination total count is absent; completeness is unknown.")

        records = page.get("results")
        records = records if isinstance(records, list) else []
        if not records:
            if expected_count is not None and len(datasets) < expected_count:
                warnings.append("Pagination ended on an empty page before the reported count.")
            break

        page_key = tuple(_source_id(record, "dataset_id", "dataset_uid") for record in records)
        if page_key in seen_pages:
            warnings.append("Pagination returned a repeated page before completion.")
            break
        seen_pages.add(page_key)

        for record in records:
            dataset, dataset_resources = _map_ods_dataset(portal_id, record, observed_at)
            datasets.append(dataset)
            resources.extend(dataset_resources)

        if expected_count is None or len(datasets) >= expected_count:
            break
    else:
        warnings.append("Pagination reached max_pages before completion.")

    complete = expected_count is not None and len(datasets) >= expected_count
    if not complete and len(pages) >= portal.max_pages and not any("max_pages" in warning for warning in warnings):
        warnings.append("Pagination reached max_pages before completion.")
    return CatalogueFetchResult(
        portal_id=portal_id,
        observed_at=observed_at,
        datasets=datasets,
        resources=resources,
        expected_count=expected_count,
        complete=complete,
        warnings=warnings,
        raw_pages=pages,
    )


def _portal_id(portal: CataloguePortalConfig) -> str:
    for portal_id, registered in CATALOGUE_PORTALS.items():
        if registered.platform is portal.platform and registered.api_base_url.rstrip("/") == portal.api_base_url.rstrip(
            "/"
        ):
            return portal_id
    raise ValueError("Catalogue portal is not registered; portal provenance is unknown")


def _map_ckan_dataset(
    portal_id: str,
    record: dict[str, Any],
    observed_at: datetime,
) -> tuple[CatalogueDataset, list[DatasetResource]]:
    source_id = _source_id(record, "name", "id")
    mapped_resources = [
        _map_resource(portal_id, source_id, item, observed_at, index)
        for index, item in enumerate(_dict_items(record.get("resources")))
    ]
    organization = record.get("organization")
    publisher = None
    if isinstance(organization, dict):
        publisher = _optional_str(organization.get("title")) or _optional_str(organization.get("name"))
    dataset = CatalogueDataset(
        id=f"{portal_id}:{source_id}",
        portal_id=portal_id,
        source_dataset_id=source_id,
        title=_optional_str(record.get("title")),
        description=_optional_str(record.get("notes")),
        publisher=publisher,
        licence=_optional_str(record.get("license_title")),
        portal_url=_optional_str(record.get("url")),
        source_created_at=_parse_source_datetime(record.get("metadata_created")),
        source_updated_at=_parse_source_datetime(record.get("metadata_modified")),
        observed_at=observed_at,
        tags=_names(record.get("tags")),
        resources=mapped_resources,
        raw_record=record,
    )
    return dataset, mapped_resources


def _map_ods_dataset(
    portal_id: str,
    record: dict[str, Any],
    observed_at: datetime,
) -> tuple[CatalogueDataset, list[DatasetResource]]:
    source_id = _source_id(record, "dataset_id", "dataset_uid")
    metas = record.get("metas")
    default = metas.get("default") if isinstance(metas, dict) else None
    default = default if isinstance(default, dict) else {}
    resource_records = _dict_items(record.get("attachments")) + _dict_items(record.get("alternative_exports"))
    mapped_resources = [
        _map_resource(portal_id, source_id, item, observed_at, index) for index, item in enumerate(resource_records)
    ]
    dataset = CatalogueDataset(
        id=f"{portal_id}:{source_id}",
        portal_id=portal_id,
        source_dataset_id=source_id,
        title=_optional_str(default.get("title")),
        description=_optional_str(default.get("description")),
        publisher=_optional_str(default.get("publisher")),
        licence=_optional_str(default.get("license")),
        source_updated_at=_parse_source_datetime(default.get("modified")),
        observed_at=observed_at,
        tags=_string_list(default.get("keyword")),
        resources=mapped_resources,
        raw_record=record,
    )
    return dataset, mapped_resources


def _map_resource(
    portal_id: str,
    source_dataset_id: str,
    record: dict[str, Any],
    observed_at: datetime,
    index: int,
) -> DatasetResource:
    source_resource_id = _optional_str(record.get("id")) or _optional_str(record.get("url")) or f"resource-{index}"
    return DatasetResource(
        id=f"{portal_id}:{source_resource_id}",
        portal_id=portal_id,
        source_dataset_id=source_dataset_id,
        name=_optional_str(record.get("name")) or _optional_str(record.get("title")),
        description=_optional_str(record.get("description")),
        url=_optional_str(record.get("url")),
        format=_optional_str(record.get("format")),
        media_type=_optional_str(record.get("mimetype")),
        size_bytes=_optional_nonnegative_int(record.get("size")),
        source_created_at=_parse_source_datetime(record.get("created")),
        source_updated_at=_parse_source_datetime(record.get("last_modified") or record.get("metadata_modified")),
        observed_at=observed_at,
        raw_record=record,
    )


def _source_id(record: Any, *fields: str) -> str:
    if isinstance(record, dict):
        for field in fields:
            value = _optional_str(record.get(field))
            if value is not None:
                return value
    raise ValueError("Catalogue record has no source dataset identifier")


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_nonnegative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _parse_source_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _names(value: Any) -> list[str]:
    return [name for item in _dict_items(value) if (name := _optional_str(item.get("name"))) is not None]


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []

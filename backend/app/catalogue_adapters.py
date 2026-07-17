"""Read-only adapters for supported public dataset catalogues."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Sequence
from urllib.parse import quote

import httpx

from app.catalogue_models import (
    CATALOGUE_PORTALS,
    CatalogueDataset,
    CataloguePortalConfig,
    ClassificationEvidence,
    DatasetResource,
    EvidenceConfidence,
    PortalPlatform,
)

PAGE_SIZE = 100

_FREQUENCY_ALIASES = {
    "daily": "daily",
    "weekly": "weekly",
    "fortnightly": "fortnightly",
    "monthly": "monthly",
    "quarterly": "quarterly",
    "biannually": "biannually",
    "semiannually": "biannually",
    "annual": "annually",
    "annually": "annually",
    "yearly": "annually",
    "continuous": "continuous",
    "realtime": "continuous",
    "real_time": "continuous",
    "event_driven": "event_driven",
    "on_event": "event_driven",
    "irregular": "irregular",
    "as_needed": "irregular",
}


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


def _default_sleep(seconds: float) -> None:
    """Default sleeper using time.sleep; replaceable for deterministic tests."""
    if seconds > 0:
        time.sleep(seconds)


def fetch_catalogue(
    portal: CataloguePortalConfig,
    client: httpx.Client,
    observed_at: datetime,
    *,
    sleeper: Callable[[float], None] = _default_sleep,
) -> CatalogueFetchResult:
    if portal.platform is PortalPlatform.ckan:
        return fetch_ckan_catalogue(portal, client, observed_at, sleeper=sleeper)
    if portal.platform is PortalPlatform.opendatasoft:
        return fetch_ods_catalogue(portal, client, observed_at, sleeper=sleeper)
    raise ValueError(f"Unsupported catalogue platform: {portal.platform}")


def fetch_ckan_catalogue(
    portal: CataloguePortalConfig,
    client: httpx.Client,
    observed_at: datetime,
    *,
    sleeper: Callable[[float], None] = _default_sleep,
) -> CatalogueFetchResult:
    portal_id = _portal_id(portal)
    url = f"{portal.api_base_url.rstrip('/')}/package_search"
    pages: list[dict[str, Any]] = []
    datasets: list[CatalogueDataset] = []
    resources: list[DatasetResource] = []
    warnings: list[str] = []
    expected_count: int | None = None
    observed_record_count = 0
    seen_pages: set[tuple[str, ...]] = set()
    seen_dataset_ids: set[str] = set()
    duplicate_dataset_id = False
    interval = 1.0 / portal.rate_limit_rps if portal.rate_limit_rps > 0 else 0.0

    for page_number in range(portal.max_pages):
        if page_number > 0:
            sleeper(interval)
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
        if not isinstance(records, list):
            raise ValueError("CKAN page results are not a usable record list")
        if not records:
            if expected_count is not None and observed_record_count < expected_count:
                warnings.append("Pagination ended on an empty page before the reported count.")
            break

        page_key = tuple(
            _source_id(record, "name", "id")
            for record in records
            if isinstance(record, dict)
            and (_optional_str(record.get("name")) or _optional_str(record.get("id")))
        )
        if not page_key:
            raise ValueError("CKAN page has no usable source dataset identifiers")
        if page_key in seen_pages:
            warnings.append("Pagination returned a repeated page before completion.")
            break
        seen_pages.add(page_key)
        observed_record_count += len(records)

        for record in records:
            if not isinstance(record, dict):
                warnings.append("Malformed CKAN record skipped: record is not a mapping")
                continue
            try:
                source_id = _source_id(record, "name", "id")
                if source_id in seen_dataset_ids:
                    duplicate_dataset_id = True
                    warnings.append(
                        "Duplicate CKAN source dataset identifier skipped: "
                        f"{source_id}"
                    )
                    continue
                resource_records, resource_warnings = _validated_resource_items(
                    record,
                    ("resources",),
                    "CKAN",
                )
                dataset, dataset_resources = _map_ckan_dataset(
                    portal_id,
                    record,
                    observed_at,
                    resource_records,
                )
                seen_dataset_ids.add(source_id)
                warnings.extend(resource_warnings)
                datasets.append(dataset)
                resources.extend(dataset_resources)
            except (TypeError, ValueError) as exc:
                warnings.append(f"Malformed CKAN record skipped: {exc}")

        if expected_count is None or observed_record_count >= expected_count:
            break
    else:
        warnings.append("Pagination reached max_pages before completion.")

    usable_count = len(seen_dataset_ids)
    complete = (
        expected_count is not None
        and usable_count == expected_count
        and not duplicate_dataset_id
    )
    if expected_count is not None and usable_count != expected_count:
        warnings.append(
            "Unique usable dataset count does not match the reported count: "
            f"expected {expected_count}, observed {usable_count}."
        )
    if not complete and len(pages) >= portal.max_pages and not any("max_pages" in warning for warning in warnings):
        warnings.append("Pagination reached max_pages before completion.")
    if any("Malformed" in w for w in warnings):
        complete = False
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
    *,
    sleeper: Callable[[float], None] = _default_sleep,
) -> CatalogueFetchResult:
    portal_id = _portal_id(portal)
    url = f"{portal.api_base_url.rstrip('/')}/catalog/datasets"
    pages: list[dict[str, Any]] = []
    datasets: list[CatalogueDataset] = []
    resources: list[DatasetResource] = []
    warnings: list[str] = []
    expected_count: int | None = None
    observed_record_count = 0
    seen_pages: set[tuple[str, ...]] = set()
    seen_dataset_ids: set[str] = set()
    duplicate_dataset_id = False
    interval = 1.0 / portal.rate_limit_rps if portal.rate_limit_rps > 0 else 0.0

    for page_number in range(portal.max_pages):
        if page_number > 0:
            sleeper(interval)
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
        if not isinstance(records, list):
            raise ValueError("ODS page results are not a usable record list")
        if not records:
            if expected_count is not None and observed_record_count < expected_count:
                warnings.append("Pagination ended on an empty page before the reported count.")
            break

        page_key = tuple(
            _source_id(record, "dataset_id", "dataset_uid")
            for record in records
            if isinstance(record, dict)
            and (
                _optional_str(record.get("dataset_id"))
                or _optional_str(record.get("dataset_uid"))
            )
        )
        if not page_key:
            raise ValueError("ODS page has no usable source dataset identifiers")
        if page_key in seen_pages:
            warnings.append("Pagination returned a repeated page before completion.")
            break
        seen_pages.add(page_key)
        observed_record_count += len(records)

        for record in records:
            if not isinstance(record, dict):
                warnings.append("Malformed ODS record skipped: record is not a mapping")
                continue
            try:
                source_id = _source_id(record, "dataset_id", "dataset_uid")
                if source_id in seen_dataset_ids:
                    duplicate_dataset_id = True
                    warnings.append(
                        "Duplicate ODS source dataset identifier skipped: "
                        f"{source_id}"
                    )
                    continue
                resource_records, resource_warnings = _validated_resource_items(
                    record,
                    ("attachments", "alternative_exports"),
                    "ODS",
                )
                dataset, dataset_resources = _map_ods_dataset(
                    portal_id,
                    record,
                    observed_at,
                    resource_records,
                )
                seen_dataset_ids.add(source_id)
                warnings.extend(resource_warnings)
                datasets.append(dataset)
                resources.extend(dataset_resources)
            except (TypeError, ValueError) as exc:
                warnings.append(f"Malformed ODS record skipped: {exc}")

        if expected_count is None or observed_record_count >= expected_count:
            break
    else:
        warnings.append("Pagination reached max_pages before completion.")

    usable_count = len(seen_dataset_ids)
    complete = (
        expected_count is not None
        and usable_count == expected_count
        and not duplicate_dataset_id
    )
    if expected_count is not None and usable_count != expected_count:
        warnings.append(
            "Unique usable dataset count does not match the reported count: "
            f"expected {expected_count}, observed {usable_count}."
        )
    if not complete and len(pages) >= portal.max_pages and not any("max_pages" in warning for warning in warnings):
        warnings.append("Pagination reached max_pages before completion.")
    if any("Malformed" in w for w in warnings):
        complete = False
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
    resource_records: Sequence[dict[str, Any]],
) -> tuple[CatalogueDataset, list[DatasetResource]]:
    source_id = _source_id(record, "name", "id")
    mapped_resources = [
        _map_resource(portal_id, source_id, item, observed_at)
        for item in resource_records
    ]
    organization = record.get("organization")
    publisher = None
    if isinstance(organization, dict):
        publisher = _optional_str(organization.get("title")) or _optional_str(organization.get("name"))
    attribution = _optional_str(record.get("attribution")) or _ckan_named_extra(
        record, "attribution"
    )
    licence_title = _optional_str(record.get("license_title"))
    licence_id = _optional_str(record.get("license_id"))
    licence_url = _optional_str(record.get("license_url"))
    tags = _names(record.get("tags"))
    themes = _titles_or_names(record.get("groups"))
    catalogue_page_url, metadata_api_url = _dataset_urls(portal_id, source_id)
    frequency_text, frequency_field = _ckan_frequency(record)
    frequency = _normalise_frequency(frequency_text)
    classification_evidence = _frequency_evidence(
        portal_id,
        source_id,
        frequency,
        frequency_text,
        frequency_field,
        observed_at,
    )
    dataset = CatalogueDataset(
        id=f"{portal_id}:{source_id}",
        portal_id=portal_id,
        source_dataset_id=source_id,
        title=_optional_str(record.get("title")),
        description=_optional_str(record.get("notes")),
        publisher=publisher,
        licence=licence_title or licence_id,
        licence_identifier=licence_id,
        licence_title=licence_title,
        licence_url=licence_url,
        attribution=attribution,
        themes=themes,
        catalogue_page_url=catalogue_page_url,
        metadata_api_url=metadata_api_url,
        declared_update_frequency=frequency,
        declared_update_frequency_text=frequency_text,
        portal_url=_optional_str(record.get("url")),
        api_url=metadata_api_url,
        source_created_at=_parse_source_datetime(record.get("metadata_created")),
        source_updated_at=_parse_source_datetime(record.get("metadata_modified")),
        observed_at=observed_at,
        tags=tags,
        resources=mapped_resources,
        classification_evidence=classification_evidence,
        raw_record=record,
    )
    return dataset, mapped_resources


def _map_ods_dataset(
    portal_id: str,
    record: dict[str, Any],
    observed_at: datetime,
    resource_records: Sequence[dict[str, Any]],
) -> tuple[CatalogueDataset, list[DatasetResource]]:
    source_id = _source_id(record, "dataset_id", "dataset_uid")
    metas = record.get("metas")
    default = metas.get("default") if isinstance(metas, dict) else None
    default = default if isinstance(default, dict) else {}
    mapped_resources = [
        _map_resource(portal_id, source_id, item, observed_at)
        for item in resource_records
    ]
    publisher = _optional_str(default.get("publisher"))
    licence_value = _optional_str(default.get("license"))
    attribution = _optional_str(default.get("attribution"))
    frequency_text, frequency_field = _first_named_text(
        default,
        ("frequency", "update_frequency", "timescale"),
        prefix="metas.default.",
    )
    frequency = _normalise_frequency(frequency_text)
    keywords = _string_list(default.get("keyword"))
    themes = _string_list(default.get("theme"))
    catalogue_page, metadata_api_url = _dataset_urls(portal_id, source_id)
    classification_evidence = _frequency_evidence(
        portal_id,
        source_id,
        frequency,
        frequency_text,
        frequency_field,
        observed_at,
    )
    dataset = CatalogueDataset(
        id=f"{portal_id}:{source_id}",
        portal_id=portal_id,
        source_dataset_id=source_id,
        title=_optional_str(default.get("title")),
        description=_optional_str(default.get("description")),
        publisher=publisher,
        licence=licence_value,
        licence_title=licence_value,
        attribution=attribution,
        themes=themes,
        catalogue_page_url=catalogue_page,
        metadata_api_url=metadata_api_url,
        declared_update_frequency=frequency,
        declared_update_frequency_text=frequency_text,
        portal_url=catalogue_page,
        api_url=metadata_api_url,
        source_updated_at=_parse_source_datetime(default.get("modified")),
        observed_at=observed_at,
        tags=keywords,
        resources=mapped_resources,
        classification_evidence=classification_evidence,
        raw_record=record,
    )
    return dataset, mapped_resources


def _map_resource(
    portal_id: str,
    source_dataset_id: str,
    record: dict[str, Any],
    observed_at: datetime,
) -> DatasetResource:
    source_resource_id = (
        _optional_str(record.get("id"))
        or _optional_str(record.get("url"))
        or _resource_content_hash(record)
    )
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
        source_updated_at=_parse_source_datetime(record.get("last_modified")),
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


def _validated_resource_items(
    record: dict[str, Any],
    fields: Sequence[str],
    platform_name: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Retain valid nested resources and report every dropped schema value."""
    resources: list[dict[str, Any]] = []
    warnings: list[str] = []
    for field in fields:
        if field not in record:
            continue
        value = record[field]
        if not isinstance(value, list):
            warnings.append(
                f"Malformed {platform_name} resource collection {field!r} "
                "skipped: expected a list."
            )
            continue
        valid_items = [item for item in value if isinstance(item, dict)]
        dropped_count = len(value) - len(valid_items)
        if dropped_count:
            warnings.append(
                f"Malformed {platform_name} resource item(s) in {field!r} "
                f"skipped: {dropped_count} item(s) were not mappings."
            )
        resources.extend(valid_items)
    return resources, warnings


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


def _titles_or_names(value: Any) -> list[str]:
    return [
        label
        for item in _dict_items(value)
        if (label := _optional_str(item.get("title")) or _optional_str(item.get("name")))
        is not None
    ]


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _resource_content_hash(record: dict[str, Any]) -> str:
    """Deterministic fallback identity from the raw resource record content."""
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    return f"resource-{digest}"


def _dataset_urls(portal_id: str, source_id: str) -> tuple[str | None, str | None]:
    """Construct public catalogue and metadata URLs from configured bases."""
    portal = CATALOGUE_PORTALS.get(portal_id)
    if portal is None:
        return None, None
    encoded_id = quote(source_id, safe="")
    if portal.platform is PortalPlatform.ckan:
        return (
            f"{portal.portal_url.rstrip('/')}/dataset/{encoded_id}",
            f"{portal.api_base_url.rstrip('/')}/package_show?id={encoded_id}",
        )
    return (
        f"{portal.portal_url.rstrip('/')}/explore/dataset/{encoded_id}/information/",
        f"{portal.api_base_url.rstrip('/')}/catalog/datasets/{encoded_id}",
    )


def _first_named_text(
    mapping: dict[str, Any],
    names: Sequence[str],
    *,
    prefix: str = "",
) -> tuple[str | None, str | None]:
    for name in names:
        value = _optional_str(mapping.get(name))
        if value is not None:
            return value, f"{prefix}{name}"
    return None, None


def _ckan_frequency(record: dict[str, Any]) -> tuple[str | None, str | None]:
    direct = _first_named_text(record, ("frequency", "update_frequency"))
    if direct[0] is not None:
        return direct
    for extra in _dict_items(record.get("extras")):
        key = _optional_str(extra.get("key"))
        if key is None or key.casefold().replace(" ", "_") not in {
            "frequency",
            "update_frequency",
        }:
            continue
        value = _optional_str(extra.get("value"))
        if value is not None:
            return value, f"extras.{key}"
    return None, None


def _ckan_named_extra(record: dict[str, Any], name: str) -> str | None:
    for extra in _dict_items(record.get("extras")):
        key = _optional_str(extra.get("key"))
        if key is not None and key.casefold().replace(" ", "_") == name:
            return _optional_str(extra.get("value"))
    return None


def _frequency_evidence(
    portal_id: str,
    source_id: str,
    canonical: str | None,
    original_text: str | None,
    source_field: str | None,
    observed_at: datetime,
) -> list[ClassificationEvidence]:
    if canonical is None or original_text is None or source_field is None:
        return []
    return [
        ClassificationEvidence(
            id=f"{portal_id}:{source_id}:portal-update-frequency",
            portal_id=portal_id,
            source_dataset_id=source_id,
            classification="portal_update_frequency",
            evidence=f"Public catalogue field {source_field} declares an update frequency.",
            confidence=EvidenceConfidence.high,
            source_value=canonical,
            observed_at=observed_at,
            raw_record={"field": source_field, "value": original_text},
        )
    ]


def _normalise_frequency(value: str | None) -> str | None:
    """Normalise a raw frequency string to a canonical form, or None if ambiguous."""
    if value is None:
        return None
    normalised = value.strip().lower().replace("-", "_").replace(" ", "_")
    if not normalised:
        return None
    return _FREQUENCY_ALIASES.get(normalised)

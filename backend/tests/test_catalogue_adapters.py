"""Behavioural tests for public catalogue adapters."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from app.catalogue_adapters import fetch_catalogue
from app.catalogue_models import CATALOGUE_PORTALS, CataloguePortalConfig, PortalPlatform

OBSERVED_AT = datetime(2026, 7, 16, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures" / "catalogue"


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeClient:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self._payloads = iter(payloads)
        self.requests: list[tuple[str, str, dict[str, int]]] = []

    def get(self, url: str, *, params: dict[str, int]) -> FakeResponse:
        self.requests.append(("GET", url, params))
        return FakeResponse(next(self._payloads))


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def ckan_page(*records: dict[str, Any], count: int | None = 2) -> dict[str, Any]:
    result: dict[str, Any] = {"results": list(records)}
    if count is not None:
        result["count"] = count
    return {"success": True, "result": result}


def ods_page(*records: dict[str, Any], count: int | None = 2) -> dict[str, Any]:
    page: dict[str, Any] = {"results": list(records)}
    if count is not None:
        page["total_count"] = count
    return page


def test_ckan_follows_result_count_until_complete():
    records = [{"name": f"dataset-{index}"} for index in range(101)]
    client = FakeClient([ckan_page(*records[:100], count=101), ckan_page(records[100], count=101)])

    result = fetch_catalogue(CATALOGUE_PORTALS["nged"], client, OBSERVED_AT)

    assert result.complete is True
    assert result.expected_count == 101
    assert len(result.datasets) == 101
    assert result.datasets[-1].source_dataset_id == "dataset-100"
    assert [request[2]["start"] for request in client.requests] == [0, 100]
    assert all(request[0] == "GET" for request in client.requests)


def test_ods_marks_short_pagination_as_incomplete():
    record = fixture("ods_page.json")["results"][0]
    client = FakeClient([ods_page(record), ods_page()])

    result = fetch_catalogue(CATALOGUE_PORTALS["spen"], client, OBSERVED_AT)

    assert result.complete is False
    assert "pagination" in " ".join(result.warnings).casefold()
    assert [request[2]["offset"] for request in client.requests] == [0, 100]
    assert all(request[0] == "GET" for request in client.requests)


@pytest.mark.parametrize(
    ("portal_id", "fixture_name", "page_factory"),
    [("nged", "ckan_page.json", ckan_page), ("spen", "ods_page.json", ods_page)],
)
def test_resources_and_datasets_retain_raw_metadata(portal_id: str, fixture_name: str, page_factory):
    payload = fixture(fixture_name)
    records = payload.get("results", payload.get("result", {}).get("results"))
    client = FakeClient([page_factory(records[0], count=1)])

    result = fetch_catalogue(CATALOGUE_PORTALS[portal_id], client, OBSERVED_AT)

    assert result.datasets[0].raw_record == records[0]
    assert result.resources[0].raw_record["source_only"] == "preserve me"
    assert result.datasets[0].resources == list(result.resources)


def test_ods_resource_maps_verified_public_fields_without_inventing_absent_facts():
    record = fixture("ods_page.json")["results"][0]
    client = FakeClient([ods_page(record, count=1)])

    result = fetch_catalogue(CATALOGUE_PORTALS["spen"], client, OBSERVED_AT)

    resource = result.resources[0]
    assert resource.id == "spen:synthetic-attachment-one"
    assert resource.name == "Synthetic attachment"
    assert resource.media_type == "text/csv"
    assert resource.url == "https://example.invalid/synthetic-attachment.csv"
    assert resource.size_bytes is None
    assert resource.source_created_at is None
    assert resource.source_updated_at is None
    assert resource.raw_record["source_only"] == "preserve me"


def test_ckan_timezone_less_dataset_and_resource_timestamps_remain_unknown():
    record = fixture("ckan_page.json")["result"]["results"][0]
    record["resources"][0]["last_modified"] = "2026-01-03T12:00:00.000000"
    client = FakeClient([ckan_page(record, count=1)])

    result = fetch_catalogue(CATALOGUE_PORTALS["nged"], client, OBSERVED_AT)

    dataset = result.datasets[0]
    resource = result.resources[0]
    assert dataset.source_created_at is None
    assert dataset.source_updated_at is None
    assert resource.source_created_at is None
    assert resource.source_updated_at is None
    assert dataset.raw_record["metadata_created"] == "2026-01-01T10:00:00.000000"
    assert dataset.raw_record["metadata_modified"] == "2026-01-02T11:00:00.000000"
    assert resource.raw_record["created"] == "2026-01-01T10:00:00.000000"
    assert resource.raw_record["last_modified"] == "2026-01-03T12:00:00.000000"


def test_ckan_offset_aware_timestamps_are_normalised_to_utc():
    record = fixture("ckan_page.json")["result"]["results"][0]
    record["metadata_modified"] = "2026-01-02T11:00:00+05:30"
    record["resources"][0]["last_modified"] = "2026-01-03T12:00:00-04:00"
    client = FakeClient([ckan_page(record, count=1)])

    result = fetch_catalogue(CATALOGUE_PORTALS["nged"], client, OBSERVED_AT)

    assert result.datasets[0].source_updated_at == datetime(2026, 1, 2, 5, 30, tzinfo=timezone.utc)
    assert result.resources[0].source_updated_at == datetime(2026, 1, 3, 16, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("platform", [PortalPlatform.ckan, PortalPlatform.opendatasoft])
def test_absent_counts_remain_unknown_and_incomplete(platform: PortalPlatform):
    registered = CATALOGUE_PORTALS["nged" if platform is PortalPlatform.ckan else "spen"]
    record = fixture("ckan_page.json")["result"]["results"][0]
    if platform is PortalPlatform.opendatasoft:
        record = fixture("ods_page.json")["results"][0]
    payload = ckan_page(record, count=None) if platform is PortalPlatform.ckan else ods_page(record, count=None)
    client = FakeClient([payload])

    result = fetch_catalogue(registered, client, OBSERVED_AT)

    assert result.expected_count is None
    assert result.complete is False
    assert result.datasets[0].source_dataset_id == "one"


def test_repeated_page_is_incomplete_and_bounded():
    record = fixture("ckan_page.json")["result"]["results"][0]
    client = FakeClient([ckan_page(record), ckan_page(record)])

    result = fetch_catalogue(CATALOGUE_PORTALS["nged"], client, OBSERVED_AT)

    assert result.complete is False
    assert len(client.requests) == 2
    assert "repeated" in " ".join(result.warnings).casefold()


def test_max_pages_is_incomplete_and_bounded():
    record = fixture("ods_page.json")["results"][0]
    portal = CataloguePortalConfig(**{**CATALOGUE_PORTALS["spen"].model_dump(), "max_pages": 1})
    client = FakeClient([ods_page(record)])

    result = fetch_catalogue(portal, client, OBSERVED_AT)

    assert result.complete is False
    assert len(client.requests) == 1
    assert "max_pages" in " ".join(result.warnings).casefold()

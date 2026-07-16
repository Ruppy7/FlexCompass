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
    records = fixture("ckan_page.json")["result"]["results"]
    client = FakeClient([ckan_page(records[0]), ckan_page(records[1])])

    result = fetch_catalogue(CATALOGUE_PORTALS["nged"], client, OBSERVED_AT)

    assert result.complete is True
    assert result.expected_count == 2
    assert [item.source_dataset_id for item in result.datasets] == ["one", "two"]
    assert [request[2]["start"] for request in client.requests] == [0, 1]
    assert all(request[0] == "GET" for request in client.requests)


def test_ods_marks_short_pagination_as_incomplete():
    record = fixture("ods_page.json")["results"][0]
    client = FakeClient([ods_page(record), ods_page()])

    result = fetch_catalogue(CATALOGUE_PORTALS["spen"], client, OBSERVED_AT)

    assert result.complete is False
    assert "pagination" in " ".join(result.warnings).casefold()
    assert [request[2]["offset"] for request in client.requests] == [0, 1]
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

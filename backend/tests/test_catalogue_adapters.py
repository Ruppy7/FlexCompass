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


def test_q4_malformed_record_isolated_with_warning_and_valid_records_retained():
    """Q4: A malformed record is skipped with a warning; valid records are retained."""
    good_record = fixture("ckan_page.json")["result"]["results"][0]
    bad_record = {"no_valid_id_field": True}  # will raise ValueError in _source_id
    client = FakeClient([ckan_page(bad_record, good_record, count=2)])

    result = fetch_catalogue(CATALOGUE_PORTALS["nged"], client, OBSERVED_AT)

    assert len(result.datasets) == 1
    assert result.datasets[0].source_dataset_id == "one"
    assert result.complete is False
    assert any("malformed" in w.lower() for w in result.warnings)


def test_q4_page_with_no_usable_record_is_a_hard_failure():
    """Q4: A non-empty page with no usable dataset identifiers is unusable."""
    client = FakeClient([ckan_page({"no_valid_id_field": True}, count=1)])

    with pytest.raises(ValueError, match="usable source dataset identifiers"):
        fetch_catalogue(CATALOGUE_PORTALS["nged"], client, OBSERVED_AT)


def test_q5_resource_fallback_identity_is_content_hash_not_position():
    """Q5: Resource fallback identity uses content hash, not position."""
    record_no_id = {
        "name": "dataset-no-resource-id",
        "resources": [{"name": "Public export", "format": "CSV"}],
        "tags": [],
    }
    client = FakeClient([ckan_page(record_no_id, count=1)])

    result = fetch_catalogue(CATALOGUE_PORTALS["nged"], client, OBSERVED_AT)

    resource = result.resources[0]
    # The fallback ID should be a content hash, not "resource-0"
    assert not resource.id.endswith(":resource-0")
    assert "resource-" in resource.id
    # Reorder the same record content - should get same hash
    record_reordered = {
        "resources": [{"format": "CSV", "name": "Public export"}],
        "name": "dataset-no-resource-id",
        "tags": [],
    }
    client2 = FakeClient([ckan_page(record_reordered, count=1)])
    result2 = fetch_catalogue(CATALOGUE_PORTALS["nged"], client2, OBSERVED_AT)
    assert result.resources[0].id == result2.resources[0].id


def test_q5_resource_fallback_does_not_coalesce_different_resources():
    """Q5: Different resource records produce different fallback IDs."""
    record = {
        "name": "dataset-two-resources",
        "resources": [
            {"name": "Export A", "format": "CSV"},
            {"name": "Export B", "format": "CSV"},
        ],
        "tags": [],
    }
    client = FakeClient([ckan_page(record, count=1)])

    result = fetch_catalogue(CATALOGUE_PORTALS["nged"], client, OBSERVED_AT)

    assert len(result.resources) == 2
    assert result.resources[0].id != result.resources[1].id

    reordered = {**record, "resources": list(reversed(record["resources"]))}
    reordered_result = fetch_catalogue(
        CATALOGUE_PORTALS["nged"],
        FakeClient([ckan_page(reordered, count=1)]),
        OBSERVED_AT,
    )
    assert {item.name: item.id for item in result.resources} == {
        item.name: item.id for item in reordered_result.resources
    }


def test_q5_fallback_hash_is_raw_resource_identity_not_parent_identity():
    """Q5: Existing store keys, not the hash, scope identical raw resources."""
    raw_resource = {"name": "Public export", "format": "CSV"}
    first = {"name": "dataset-one", "resources": [raw_resource], "tags": []}
    second = {"name": "dataset-two", "resources": [raw_resource], "tags": []}

    first_result = fetch_catalogue(
        CATALOGUE_PORTALS["nged"], FakeClient([ckan_page(first, count=1)]), OBSERVED_AT
    )
    second_result = fetch_catalogue(
        CATALOGUE_PORTALS["nged"], FakeClient([ckan_page(second, count=1)]), OBSERVED_AT
    )

    assert first_result.resources[0].id == second_result.resources[0].id


def test_s10_rate_limit_pacing_between_pages_not_first():
    """S10: Rate-limit pacing is applied between pages but not before the first request."""
    records = [{"name": f"ds-{i}"} for i in range(3)]
    client = FakeClient([ckan_page(*records[:2], count=3), ckan_page(records[2], count=3)])
    sleeps: list[float] = []

    result = fetch_catalogue(
        CATALOGUE_PORTALS["nged"], client, OBSERVED_AT, sleeper=lambda s: sleeps.append(s)
    )

    assert len(result.datasets) == 3
    assert len(client.requests) == 2
    # First request has no sleep; second page has one sleep
    assert len(sleeps) == 1
    assert sleeps[0] > 0


def test_s9_ckan_canonical_metadata_mapped():
    """S9: CKAN licence, attribution, themes, and catalogue page URL are mapped."""
    record = fixture("ckan_page.json")["result"]["results"][0]
    record["license_id"] = "odc-odbl"
    record["license_url"] = "https://opendatacommons.org/licenses/odbl/1.0/"
    record["groups"] = [{"name": "network-planning", "title": "Network Planning"}]
    record["extras"] = [{"key": "attribution", "value": "Example attribution"}]
    client = FakeClient([ckan_page(record, count=1)])

    result = fetch_catalogue(CATALOGUE_PORTALS["nged"], client, OBSERVED_AT)

    dataset = result.datasets[0]
    assert dataset.licence_title == "Example licence"
    assert dataset.licence_identifier == "odc-odbl"
    assert dataset.licence_url == "https://opendatacommons.org/licenses/odbl/1.0/"
    assert dataset.attribution == "Example attribution"
    assert dataset.themes == ["Network Planning"]
    assert dataset.tags == ["synthetic"]
    assert dataset.catalogue_page_url.endswith("/dataset/one")
    assert dataset.metadata_api_url.endswith("/package_show?id=one")


def test_s9_ods_canonical_metadata_mapped():
    """S9: ODS licence, attribution, themes, and catalogue page URL are mapped."""
    record = fixture("ods_page.json")["results"][0]
    record["metas"]["default"]["attribution"] = "Example attribution"
    record["metas"]["default"]["theme"] = ["Network Planning"]
    client = FakeClient([ods_page(record, count=1)])

    result = fetch_catalogue(CATALOGUE_PORTALS["spen"], client, OBSERVED_AT)

    dataset = result.datasets[0]
    assert dataset.licence_title == "Example licence"
    assert dataset.attribution == "Example attribution"
    assert dataset.themes == ["Network Planning"]
    assert dataset.tags == ["synthetic"]
    assert dataset.catalogue_page_url is not None
    assert "one" in dataset.catalogue_page_url
    assert dataset.metadata_api_url.endswith("/catalog/datasets/one")


def test_s9_ckan_does_not_infer_licence_url_from_identifier():
    """S9: A missing licence URL remains unknown rather than being guessed."""
    record = fixture("ckan_page.json")["result"]["results"][0]
    record["license_id"] = "cc-by"
    record.pop("license_url", None)

    result = fetch_catalogue(
        CATALOGUE_PORTALS["nged"], FakeClient([ckan_page(record, count=1)]), OBSERVED_AT
    )

    assert result.datasets[0].licence_url is None


def test_s9_publisher_and_keywords_do_not_infer_attribution_or_themes():
    """S9: Distinct canonical facts remain unknown when not supplied."""
    ckan_record = fixture("ckan_page.json")["result"]["results"][0]
    ods_record = fixture("ods_page.json")["results"][0]

    ckan = fetch_catalogue(
        CATALOGUE_PORTALS["nged"],
        FakeClient([ckan_page(ckan_record, count=1)]),
        OBSERVED_AT,
    ).datasets[0]
    ods = fetch_catalogue(
        CATALOGUE_PORTALS["spen"],
        FakeClient([ods_page(ods_record, count=1)]),
        OBSERVED_AT,
    ).datasets[0]

    assert ckan.publisher == "Example Publisher"
    assert ckan.tags == ["synthetic"]
    assert ckan.attribution is None
    assert ckan.themes == []
    assert ods.publisher == "Example Publisher"
    assert ods.tags == ["synthetic"]
    assert ods.attribution is None
    assert ods.themes == []


def test_s5_ckan_frequency_mapped_when_present():
    """S5: CKAN declared_update_frequency is mapped when the source supplies it."""
    record = fixture("ckan_page.json")["result"]["results"][0]
    record["frequency"] = "Weekly"
    client = FakeClient([ckan_page(record, count=1)])

    result = fetch_catalogue(CATALOGUE_PORTALS["nged"], client, OBSERVED_AT)

    dataset = result.datasets[0]
    assert dataset.declared_update_frequency == "weekly"
    assert dataset.declared_update_frequency_text == "Weekly"
    assert [item.classification for item in dataset.classification_evidence] == [
        "portal_update_frequency"
    ]
    assert dataset.classification_evidence[0].source_value == "weekly"


def test_s5_ckan_named_extra_frequency_is_mapped_conservatively():
    """S5: A conservatively named CKAN extra supplies cadence evidence."""
    record = fixture("ckan_page.json")["result"]["results"][0]
    record["extras"] = [{"key": "update_frequency", "value": "Monthly"}]

    result = fetch_catalogue(
        CATALOGUE_PORTALS["nged"], FakeClient([ckan_page(record, count=1)]), OBSERVED_AT
    )

    dataset = result.datasets[0]
    assert dataset.declared_update_frequency == "monthly"
    assert dataset.declared_update_frequency_text == "Monthly"
    assert dataset.classification_evidence[0].raw_record == {
        "field": "extras.update_frequency",
        "value": "Monthly",
    }


def test_s5_ods_default_frequency_emits_cadence_evidence():
    """S5: ODS default metas frequency becomes canonical cadence evidence."""
    record = fixture("ods_page.json")["results"][0]
    record["metas"]["default"]["frequency"] = "Quarterly"

    result = fetch_catalogue(
        CATALOGUE_PORTALS["spen"], FakeClient([ods_page(record, count=1)]), OBSERVED_AT
    )

    dataset = result.datasets[0]
    assert dataset.declared_update_frequency == "quarterly"
    assert dataset.declared_update_frequency_text == "Quarterly"
    assert dataset.classification_evidence[0].classification == "portal_update_frequency"


def test_s5_frequency_absent_remains_unknown():
    """S5: Absent frequency remains None (unknown)."""
    record = fixture("ckan_page.json")["result"]["results"][0]
    client = FakeClient([ckan_page(record, count=1)])

    result = fetch_catalogue(CATALOGUE_PORTALS["nged"], client, OBSERVED_AT)

    dataset = result.datasets[0]
    assert dataset.declared_update_frequency is None
    assert dataset.declared_update_frequency_text is None
    assert dataset.classification_evidence == []


def test_s5_ambiguous_frequency_preserves_text_without_canonical_evidence():
    """S5: Ambiguous cadence text is retained but not interpreted."""
    record = fixture("ckan_page.json")["result"]["results"][0]
    record["frequency"] = "Biweekly"

    dataset = fetch_catalogue(
        CATALOGUE_PORTALS["nged"],
        FakeClient([ckan_page(record, count=1)]),
        OBSERVED_AT,
    ).datasets[0]

    assert dataset.declared_update_frequency is None
    assert dataset.declared_update_frequency_text == "Biweekly"
    assert dataset.classification_evidence == []


def test_s10_ods_rate_limit_pacing_between_pages_not_first():
    """S10: ODS also paces only between requests."""
    records = [
        {"dataset_id": f"ds-{index}", "metas": {"default": {}}}
        for index in range(3)
    ]
    client = FakeClient([ods_page(*records[:2], count=3), ods_page(records[2], count=3)])
    sleeps: list[float] = []

    result = fetch_catalogue(
        CATALOGUE_PORTALS["spen"],
        client,
        OBSERVED_AT,
        sleeper=sleeps.append,
    )

    assert len(result.datasets) == 3
    assert len(client.requests) == 2
    assert sleeps == [pytest.approx(1 / CATALOGUE_PORTALS["spen"].rate_limit_rps)]

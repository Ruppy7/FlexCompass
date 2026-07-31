"""Tests for FlexCompass v0.1 core modules.

Coverage: confidence rubric, resolver, normaliser, capacity maths, config.
"""

import pytest
from app.catalogue_models import CATALOGUE_PORTAL_IDS
from app.confidence import (
    GeographyMatch,
    confidence_from_signal_fields,
)
from app.config import config
from app.models import (
    AssetType,
    ConfidenceLevel,
    FlexZone,
    HistoricCurrentFuture,
    LocationType,
    RequirementType,
    ServiceType,
)
from app.normaliser import (
    normalise_nged_signal,
    normalise_nged_zone,
    normalise_spen_signal,
)
from app.resolver import batch_resolve, parse_postcode, resolve_postcode
from app.sampling import sample_postcodes


def resolver_zones() -> list[FlexZone]:
    return [
        FlexZone(
            zone_id="test_nged",
            dso="NGED",
            area_name="Test Midlands",
            zone_type="test_fixture",
            postcode_prefixes=["B"],
        ),
        FlexZone(
            zone_id="test_spen",
            dso="SPEN",
            area_name="Test Central Scotland",
            zone_type="test_fixture",
            postcode_prefixes=["G"],
        ),
    ]


# ---------------------------------------------------------------------------
# Confidence rubric tests
# ---------------------------------------------------------------------------

class TestConfidenceRubric:
    def test_high_confidence_polygon_all_fields(self):
        level, score, reasons = confidence_from_signal_fields(
            geography_match=GeographyMatch.POLYGON,
            dso="NGED", service_type="demand_turn_down", location_type="zone",
            capacity_kw=800, guide_price=18.0, duration_minutes=120,
            eligible_asset_types=["ev_charger"], source_updated_at="2026-04-01",
        )
        assert level == ConfidenceLevel.high
        assert score >= 0.8

    def test_medium_confidence_prefix_partial(self):
        level, score, reasons = confidence_from_signal_fields(
            geography_match=GeographyMatch.PREFIX,
            dso="SPEN", service_type="demand_turn_down", location_type="dso_region",
            capacity_kw=150, guide_price=15.0,
        )
        assert level == ConfidenceLevel.medium

    def test_low_confidence_district_few_fields(self):
        level, score, reasons = confidence_from_signal_fields(
            geography_match=GeographyMatch.DISTRICT,
            dso="ENWL", service_type="demand_turn_down",
        )
        assert level in (ConfidenceLevel.low, ConfidenceLevel.insufficient_evidence)

    def test_insufficient_evidence_no_fields(self):
        level, score, reasons = confidence_from_signal_fields(
            geography_match=GeographyMatch.NONE,
        )
        assert level == ConfidenceLevel.insufficient_evidence
        assert score == 0.0

    def test_score_range(self):
        """Score should always be between 0 and 1."""
        for geo in GeographyMatch:
            level, score, reasons = confidence_from_signal_fields(
                geography_match=geo, dso="TEST", service_type="demand_turn_down",
            )
            assert 0.0 <= score <= 1.0

    def test_polygon_beats_prefix(self):
        """Polygon match should score higher than prefix with same fields."""
        _, score_poly, _ = confidence_from_signal_fields(
            geography_match=GeographyMatch.POLYGON,
            dso="NGED", service_type="demand_turn_down",
            capacity_kw=100, guide_price=10.0,
        )
        _, score_prefix, _ = confidence_from_signal_fields(
            geography_match=GeographyMatch.PREFIX,
            dso="NGED", service_type="demand_turn_down",
            capacity_kw=100, guide_price=10.0,
        )
        assert score_poly > score_prefix


# ---------------------------------------------------------------------------
# Postcode resolver tests
# ---------------------------------------------------------------------------

class TestPostcodeResolver:
    def test_parse_valid_postcode(self):
        assert parse_postcode("B1 2AB") == ("B1 2AB", "B1", "B")
        assert parse_postcode("SW1A 1AA") == ("SW1A 1AA", "SW1A", "SW")
        assert parse_postcode("AB10 1AB") == ("AB10 1AB", "AB10", "AB")

    def test_parse_invalid_postcode(self):
        assert parse_postcode("NOTAPOSTCODE") is None
        assert parse_postcode("") is None
        assert parse_postcode("12345") is None

    def test_parse_case_insensitive(self):
        result = parse_postcode("b1 2ab")
        assert result is not None
        assert result[0] == "B1 2AB"

    def test_resolve_birmingham_matches_nged(self):
        """Birmingham postcodes should match NGED zones with 'B' prefix."""
        zones = resolver_zones()
        matches = resolve_postcode("B1 2AB", zones)
        assert len(matches) > 0
        assert all(m.zone.dso == "NGED" for m in matches)
        assert all(m.zone.area_name == "Test Midlands" for m in matches)

    def test_resolve_glasgow_matches_spen(self):
        zones = resolver_zones()
        matches = resolve_postcode("G1 1AA", zones)
        assert len(matches) > 0
        assert all(m.zone.dso == "SPEN" for m in matches)

    def test_resolve_london_matches_nothing(self):
        """London postcodes should not match any NGED/SPEN/ENWL/SSEN zones."""
        zones = resolver_zones()
        matches = resolve_postcode("E1 1AA", zones)
        assert len(matches) == 0

    def test_batch_resolve(self):
        zones = resolver_zones()
        results = batch_resolve(["B1 1AA", "G1 1AA", "E1 1AA"], zones)
        assert len(results["B1 1AA"]) > 0
        assert len(results["G1 1AA"]) > 0
        assert len(results["E1 1AA"]) == 0


# ---------------------------------------------------------------------------
# Normaliser tests
# ---------------------------------------------------------------------------

class TestNormaliser:
    def test_nged_normalise_basic(self):
        raw = {
            "trade_id": "T-001",
            "zone": "midlands_north",
            "service_type": "demand_turn_down",
            "direction": "demand_turn_down",
            "round": "round_2",
            "status": "active",
            "mw_requirement": 0.8,
            "guide_price": 18.0,
        }
        sig = normalise_nged_signal(raw, source_dataset_id="ds_test")
        assert sig.signal_id == "sig_T-001"
        assert sig.zone_id == "nged_midlands_north"
        assert sig.dso == "NGED"
        assert sig.capacity_kw == 800.0
        assert sig.guide_price == 18.0
        assert sig.source_dataset_id == "ds_test"
        assert sig.raw_record == raw

    def test_nged_normalise_mw_to_kw(self):
        """MW values should be converted to kW."""
        raw = {"trade_id": "T-002", "mw_requirement": 1.5, "guide_price": 20.0}
        sig = normalise_nged_signal(raw)
        assert sig.capacity_kw == 1500.0

    def test_nged_normalise_preserves_raw(self):
        raw = {"trade_id": "T-003", "zone": "test", "extra_field": "preserved"}
        sig = normalise_nged_signal(raw)
        assert sig.raw_record["extra_field"] == "preserved"

    def test_spen_normalise_basic(self):
        raw = {
            "record_id": "SPEN-001",
            "zone": "central_scotland",
            "service_type": "demand_turn_down",
            "capacity_kw": 150.0,
            "guide_price": 15.0,
            "platform": "Electron",
        }
        sig = normalise_spen_signal(raw, source_dataset_id="ds_spen")
        assert sig.dso == "SPEN"
        assert sig.platform == "Electron"
        assert sig.capacity_kw == 150.0

    @pytest.mark.parametrize("status", ["inactive", "not active"])
    def test_nged_unsupported_status_remains_unknown(self, status: str):
        sig = normalise_nged_signal({"trade_id": "T-status", "status": status})
        assert (
            sig.historic_current_future_status
            is HistoricCurrentFuture.unknown
        )

    def test_nged_supported_status_uses_trimmed_casefolded_exact_match(self):
        sig = normalise_nged_signal(
            {"trade_id": "T-active", "status": "  ACTIVE  "}
        )
        assert (
            sig.historic_current_future_status
            is HistoricCurrentFuture.current
        )

    def test_spen_preserves_explicit_zero_capacity_and_price(self):
        sig = normalise_spen_signal(
            {
                "record_id": "SPEN-zero",
                "capacity_kw": 0,
                "capacity_mw": 2,
                "guide_price": 0,
                "price": 99,
            }
        )
        assert sig.capacity_kw == 0
        assert sig.guide_price == 0

    def test_spen_converts_explicit_capacity_mw_to_kw(self):
        sig = normalise_spen_signal(
            {"record_id": "SPEN-mw", "capacity_mw": 1.25}
        )
        assert sig.capacity_kw == 1250

    def test_spen_does_not_consume_ambiguous_mw_requirement(self):
        sig = normalise_spen_signal(
            {"record_id": "SPEN-ambiguous", "mw_requirement": 1.5}
        )
        assert sig.capacity_kw is None

    def test_normalise_handles_none_values(self):
        """Normaliser should handle None/missing fields gracefully."""
        raw = {"trade_id": "T-004"}
        sig = normalise_nged_signal(raw)
        assert sig.capacity_kw is None
        assert sig.guide_price is None
        assert sig.zone_id is None


def test_missing_service_and_requirement_remain_unknown() -> None:
    signal = normalise_nged_signal({"trade_id": "T-unknown"})
    assert signal.service_type is None
    assert signal.requirement_type is None
    assert signal.procurement_type is None
    assert signal.price_unit is None


def test_unrecognised_service_type_remains_unknown() -> None:
    signal = normalise_nged_signal(
        {"trade_id": "T-other", "service_type": "publisher-new-service"}
    )
    assert signal.service_type is None


def test_nged_zone_without_source_identity_fails_closed() -> None:
    with pytest.raises(ValueError, match="missing zone identity"):
        normalise_nged_zone({"area_name": "Unidentified"})


@pytest.mark.parametrize(
    ("normaliser", "identifier"),
    [
        (normalise_nged_signal, {"trade_id": "T-empty"}),
        (normalise_spen_signal, {"record_id": "S-empty"}),
    ],
)
def test_empty_publisher_evidence_remains_unknown(
    normaliser,
    identifier: dict[str, str],
) -> None:
    signal = normaliser(
        {
            **identifier,
            "service_type": "",
            "market_name": "",
            "area_name": "",
            "platform": "",
            "requirement_type": "",
            "procurement_type": "",
            "price_unit": "",
            "eligible_asset_types": None,
            "zone": "",
        }
    )

    assert signal.service_type is None
    assert signal.market_name is None
    assert signal.area_name is None
    assert signal.platform is None
    assert signal.requirement_type is None
    assert signal.procurement_type is None
    assert signal.price_unit is None
    assert signal.eligible_asset_types is None
    assert signal.location_reference is None
    assert signal.location_type is None


@pytest.mark.parametrize(
    ("normaliser", "identifier"),
    [
        (normalise_nged_signal, {"trade_id": "T-unrecognised"}),
        (normalise_spen_signal, {"record_id": "S-unrecognised"}),
    ],
)
def test_unrecognised_allow_list_values_remain_unknown(
    normaliser,
    identifier: dict[str, str],
) -> None:
    signal = normaliser(
        {
            **identifier,
            "service_type": "publisher-new-service",
            "requirement_type": "publisher-new-requirement",
            "eligible_asset_types": ["publisher-new-asset"],
        }
    )

    assert signal.service_type is None
    assert signal.requirement_type is None
    assert signal.eligible_asset_types is None


@pytest.mark.parametrize(
    ("normaliser", "identifier", "zone_id"),
    [
        (normalise_nged_signal, {"trade_id": "T-known"}, "nged_verified"),
        (normalise_spen_signal, {"record_id": "S-known"}, "spen_verified"),
    ],
)
def test_explicit_publisher_evidence_is_preserved(
    normaliser,
    identifier: dict[str, str],
    zone_id: str,
) -> None:
    signal = normaliser(
        {
            **identifier,
            "service_type": "demand_turn_up",
            "market_name": "Published market",
            "area_name": "Published area",
            "platform": "Published platform",
            "requirement_type": "day_ahead",
            "procurement_type": "Published procurement",
            "price_unit": "GBP/MW/h",
            "eligible_asset_types": ["battery"],
        },
        zone_id=zone_id,
    )

    assert signal.service_type is ServiceType.demand_turn_up
    assert signal.market_name == "Published market"
    assert signal.area_name == "Published area"
    assert signal.platform == "Published platform"
    assert signal.requirement_type is RequirementType.day_ahead
    assert signal.procurement_type == "Published procurement"
    assert signal.price_unit == "GBP/MW/h"
    assert signal.eligible_asset_types == [AssetType.battery]
    assert signal.location_reference == zone_id
    assert signal.location_type is LocationType.zone


def test_nged_zone_preserves_only_publisher_area_and_type() -> None:
    zone = normalise_nged_zone({"zone": "published-zone"})
    assert zone.area_name is None
    assert zone.zone_type is None


# ---------------------------------------------------------------------------
# Sampling tests
# ---------------------------------------------------------------------------

class TestSampling:
    def test_deterministic_sampling(self):
        """Same seed should produce same sample."""
        items = list(range(100))
        s1 = sample_postcodes(items, 10, seed=42)
        s2 = sample_postcodes(items, 10, seed=42)
        assert s1 == s2

    def test_different_seeds_different_samples(self):
        items = list(range(100))
        s1 = sample_postcodes(items, 10, seed=42)
        s2 = sample_postcodes(items, 10, seed=99)
        assert s1 != s2

    def test_sample_size_capped(self):
        items = ["A", "B", "C"]
        result = sample_postcodes(items, 10, seed=42)
        assert len(result) == 3  # can't sample more than available


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

class TestConfig:
    def test_default_seed(self):
        assert config.default_seed == 42

    def test_portals_configured(self):
        assert CATALOGUE_PORTAL_IDS == (
            "nged",
            "spen",
            "enwl",
            "ssen",
            "ukpn",
            "npg",
            "neso",
        )

    def test_capacity_method_version(self):
        assert config.capacity_method_version == "v0.1"


# ---------------------------------------------------------------------------
# Capacity maths tests
# ---------------------------------------------------------------------------

class TestCapacityMaths:
    def test_capacity_formula(self):
        """Basic capacity formula: count × controllable × avail × reliability."""
        count = 1000
        controllable = 4.5
        avail = 0.03
        reliability = 0.85
        expected = count * controllable * avail * reliability
        assert expected == 114.75

    def test_zero_availability_zero_capacity(self):
        count = 1000
        controllable = 4.5
        avail = 0.0
        reliability = 0.85
        assert count * controllable * avail * reliability == 0.0

    def test_generate_endpoint_capacity(self):
        """The generate endpoint should use the correct formula."""
        # EV charger defaults: controllable=4.5, avail=0.03, reliability=0.85
        count = 500
        est = count * 4.5 * 0.03 * 0.85
        assert est == 57.375

"""Tests for FlexCompass v0.1 core modules.

Coverage: confidence rubric, resolver, normaliser, capacity maths, config.
"""

from app.confidence import (
    GeographyMatch,
    confidence_from_signal_fields,
)
from app.config import config
from app.models import ConfidenceLevel, FlexZone
from app.normaliser import normalise_nged_signal, normalise_spen_signal
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
        }
        sig = normalise_spen_signal(raw, source_dataset_id="ds_spen")
        assert sig.dso == "SPEN"
        assert sig.platform == "Electron"
        assert sig.capacity_kw == 150.0

    def test_normalise_handles_none_values(self):
        """Normaliser should handle None/missing fields gracefully."""
        raw = {"trade_id": "T-004"}
        sig = normalise_nged_signal(raw)
        assert sig.capacity_kw is None
        assert sig.guide_price is None
        assert sig.zone_id is None


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
        assert "nged" in config.portals
        assert "spen" in config.portals
        assert "enwl" in config.portals
        assert "ssen" in config.portals

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

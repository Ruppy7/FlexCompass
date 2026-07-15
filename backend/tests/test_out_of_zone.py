"""Out-of-zone postcode sampling tests for FlexCompass.

Tests the negative path: postcodes that should NOT match any zone.
Ensures the resolver returns empty match lists and does not assign
confidence levels for postcodes outside a DSO's geographic coverage.
"""

import pytest
from app.models import FlexZone
from app.resolver import resolve_postcode

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def zones():
    """Use explicit test-only regions; repository data starts empty."""
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
            area_name="Test Central Scotland and North Wales",
            zone_type="test_fixture",
            postcode_prefixes=["G", "LL"],
        ),
        FlexZone(
            zone_id="test_enwl",
            dso="ENWL",
            area_name="Test North West",
            zone_type="test_fixture",
            postcode_prefixes=["M", "LA"],
        ),
        FlexZone(
            zone_id="test_ssen",
            dso="SSEN",
            area_name="Test North Scotland",
            zone_type="test_fixture",
            postcode_prefixes=["IV", "KW"],
        ),
    ]


# ---------------------------------------------------------------------------
# 1) London postcodes against non-London DSO zones
#    London (E, W, N, SE, SW) is covered by UKPN/SPN, not by NGED/SPEN/ENWL/SSEN.
# ---------------------------------------------------------------------------

LONDON_POSTCODES = ["E1 1AA", "W1 1AA", "N1 1AA", "SE1 1AA", "SW1 1AA"]
NON_LONDON_DSOS = ["NGED", "SPEN", "ENWL", "SSEN"]


class TestLondonPostcodesOutOfZone:
    """London postcodes must not match any NGED, SPEN, ENWL, or SSEN zone."""

    @pytest.mark.parametrize("postcode", LONDON_POSTCODES)
    def test_london_postcode_returns_no_matches(self, postcode, zones):
        matches = resolve_postcode(postcode, zones)
        assert len(matches) == 0, (
            f"London postcode {postcode} should not match any zone, "
            f"but got {len(matches)} match(es): "
            f"{[m.zone.zone_id for m in matches]}"
        )

    @pytest.mark.parametrize("postcode", LONDON_POSTCODES)
    def test_london_postcode_no_dso_matches(self, postcode, zones):
        """Verify no matches against each non-London DSO individually."""
        matches = resolve_postcode(postcode, zones)
        matched_dsos = {m.zone.dso for m in matches}
        for dso in NON_LONDON_DSOS:
            assert dso not in matched_dsos, (
                f"London postcode {postcode} should not match DSO {dso}"
            )

    @pytest.mark.parametrize("postcode", LONDON_POSTCODES)
    def test_london_postcode_no_confidence_assigned(self, postcode, zones):
        """No-match results must not carry a meaningful confidence level."""
        matches = resolve_postcode(postcode, zones)
        assert len(matches) == 0, (
            f"Expected empty matches for {postcode}, got {len(matches)}"
        )
        # With no matches, there are no PostcodeMatch objects at all,
        # so no confidence level is set on any result.
        for m in matches:
            assert m.confidence is None, (
                f"Unexpected confidence {m.confidence} on no-match result"
            )


# ---------------------------------------------------------------------------
# 2) Scottish highland postcodes against non-SSEN zones
#    IV and KW are in SSEN North Scotland, NOT in NGED/SPEN/ENWL.
# ---------------------------------------------------------------------------

HIGHLAND_POSTCODES = ["IV1 1AA", "KW1 1AA"]
NON_SSEN_DSOS = ["NGED", "SPEN", "ENWL"]


class TestScottishHighlandOutOfZone:
    """Scottish highland postcodes must not match NGED, SPEN, or ENWL zones."""

    @pytest.mark.parametrize("postcode", HIGHLAND_POSTCODES)
    def test_highland_not_in_nged(self, postcode, zones):
        matches = resolve_postcode(postcode, zones)
        nged_matches = [m for m in matches if m.zone.dso == "NGED"]
        assert len(nged_matches) == 0, (
            f"Highland postcode {postcode} should not match NGED, "
            f"but matched: {[m.zone.zone_id for m in nged_matches]}"
        )

    @pytest.mark.parametrize("postcode", HIGHLAND_POSTCODES)
    def test_highland_not_in_spen(self, postcode, zones):
        matches = resolve_postcode(postcode, zones)
        spen_matches = [m for m in matches if m.zone.dso == "SPEN"]
        assert len(spen_matches) == 0, (
            f"Highland postcode {postcode} should not match SPEN, "
            f"but matched: {[m.zone.zone_id for m in spen_matches]}"
        )

    @pytest.mark.parametrize("postcode", HIGHLAND_POSTCODES)
    def test_highland_not_in_enwl(self, postcode, zones):
        matches = resolve_postcode(postcode, zones)
        enwl_matches = [m for m in matches if m.zone.dso == "ENWL"]
        assert len(enwl_matches) == 0, (
            f"Highland postcode {postcode} should not match ENWL, "
            f"but matched: {[m.zone.zone_id for m in enwl_matches]}"
        )

    @pytest.mark.parametrize("postcode", HIGHLAND_POSTCODES)
    def test_highland_matches_ssen_only(self, postcode, zones):
        """Highland postcodes SHOULD match SSEN — sanity check."""
        matches = resolve_postcode(postcode, zones)
        assert len(matches) > 0, f"Highland postcode {postcode} should match SSEN"
        assert all(m.zone.dso == "SSEN" for m in matches), (
            f"Highland postcode {postcode} should only match SSEN, "
            f"but matched DSOs: {set(m.zone.dso for m in matches)}"
        )


# ---------------------------------------------------------------------------
# 3) Welsh postcodes against non-SPEN zones
#    LL is in SPEN North Wales & Merseyside, NOT in NGED/ENWL/SSEN.
# ---------------------------------------------------------------------------

WELSH_POSTCODES = ["LL1 1AA"]
NON_SPEN_DSOS = ["NGED", "ENWL", "SSEN"]


class TestWelshPostcodesOutOfZone:
    """Welsh LL postcodes must not match NGED, ENWL, or SSEN zones."""

    @pytest.mark.parametrize("postcode", WELSH_POSTCODES)
    def test_welsh_not_in_nged(self, postcode, zones):
        matches = resolve_postcode(postcode, zones)
        nged_matches = [m for m in matches if m.zone.dso == "NGED"]
        assert len(nged_matches) == 0, (
            f"Welsh postcode {postcode} should not match NGED, "
            f"but matched: {[m.zone.zone_id for m in nged_matches]}"
        )

    @pytest.mark.parametrize("postcode", WELSH_POSTCODES)
    def test_welsh_not_in_enwl(self, postcode, zones):
        matches = resolve_postcode(postcode, zones)
        enwl_matches = [m for m in matches if m.zone.dso == "ENWL"]
        assert len(enwl_matches) == 0, (
            f"Welsh postcode {postcode} should not match ENWL, "
            f"but matched: {[m.zone.zone_id for m in enwl_matches]}"
        )

    @pytest.mark.parametrize("postcode", WELSH_POSTCODES)
    def test_welsh_not_in_ssen(self, postcode, zones):
        matches = resolve_postcode(postcode, zones)
        ssen_matches = [m for m in matches if m.zone.dso == "SSEN"]
        assert len(ssen_matches) == 0, (
            f"Welsh postcode {postcode} should not match SSEN, "
            f"but matched: {[m.zone.zone_id for m in ssen_matches]}"
        )

    @pytest.mark.parametrize("postcode", WELSH_POSTCODES)
    def test_welsh_matches_spen_only(self, postcode, zones):
        """Welsh LL postcodes SHOULD match SPEN — sanity check."""
        matches = resolve_postcode(postcode, zones)
        assert len(matches) > 0, f"Welsh postcode {postcode} should match SPEN"
        assert all(m.zone.dso == "SPEN" for m in matches), (
            f"Welsh postcode {postcode} should only match SPEN, "
            f"but matched DSOs: {set(m.zone.dso for m in matches)}"
        )


# ---------------------------------------------------------------------------
# 4) Resolver returns empty match lists for out-of-zone postcodes
# ---------------------------------------------------------------------------

# Postcodes deliberately absent from the explicit test fixtures above.
TOTALLY_OUT_OF_ZONE = [
    ("E1 1AA", "London East"),      # UKPN territory
    ("W1 1AA", "London West"),      # UKPN territory
    ("N1 1AA", "London North"),     # UKPN territory
    ("SE1 1AA", "London South East"),  # UKPN territory
    ("SW1 1AA", "London South West"),  # UKPN / SPN territory
    ("NR1 1AA", "Norwich"),         # UKPN territory (Anglia)
    ("IP1 1AA", "Ipswich"),         # UKPN territory (Anglia)
    ("AL1 1AA", "St Albans"),       # UKPN territory
]


class TestResolverEmptyResults:
    """Resolver must return an empty list for postcodes with no zone coverage."""

    @pytest.mark.parametrize("postcode,region", TOTALLY_OUT_OF_ZONE)
    def test_returns_empty_list(self, postcode, region, zones):
        matches = resolve_postcode(postcode, zones)
        assert isinstance(matches, list), (
            f"Expected list for {postcode} ({region}), got {type(matches)}"
        )
        assert len(matches) == 0, (
            f"{postcode} ({region}) should return empty match list, "
            f"but got {len(matches)} match(es): "
            f"{[m.zone.zone_id for m in matches]}"
        )

    @pytest.mark.parametrize("postcode,region", TOTALLY_OUT_OF_ZONE)
    def test_result_is_falsy_when_empty(self, postcode, region, zones):
        """Empty match list should be falsy for easy boolean checks."""
        matches = resolve_postcode(postcode, zones)
        assert not matches, (
            f"{postcode} ({region}) should be falsy (empty list)"
        )


# ---------------------------------------------------------------------------
# 5) Confidence level is not set for no-match results
# ---------------------------------------------------------------------------

class TestNoConfidenceForNoMatch:
    """When the resolver finds no zone match, no confidence should be assigned."""

    @pytest.mark.parametrize("postcode", LONDON_POSTCODES + ["NR1 1AA", "IP1 1AA"])
    def test_no_matches_means_no_confidence(self, postcode, zones):
        """With zero matches, there are no PostcodeMatch objects,
        so confidence is inherently not set on any result."""
        matches = resolve_postcode(postcode, zones)
        assert len(matches) == 0
        # The match list is empty — no objects exist to carry confidence.
        # This is the correct negative-path behaviour.

    def test_batch_resolve_no_match_returns_empty(self, zones):
        """batch_resolve should return empty lists for out-of-zone postcodes."""
        from app.resolver import batch_resolve

        postcodes = ["E1 1AA", "N1 1AA", "W1 1AA"]
        results = batch_resolve(postcodes, zones)
        for pc in postcodes:
            assert pc in results, f"{pc} missing from batch results"
            assert len(results[pc]) == 0, (
                f"{pc} should have empty matches in batch, "
                f"got {len(results[pc])}"
            )

    def test_confidence_enum_not_mutated(self, zones):
        """Resolver should not create matches with default/confused confidence
        for postcodes it cannot resolve."""

        matches = resolve_postcode("E1 1AA", zones)
        assert len(matches) == 0
        # No match objects means no ConfidenceLevel values leaked into results.
        # This test exists to guard against a future regression where the
        # resolver might return a "zero-confidence" match instead of empty.

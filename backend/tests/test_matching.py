"""Unit tests for the 7-check matching logic in app.matching."""


from app.matching import (
    _check_asset_compatibility,
    _check_capacity,
    _check_data_completeness,
    _check_geography,
    _check_market_rule,
    _check_temporal,
    _determine_priority,
    assess_portfolio,
)
from app.models import (
    AssetGroup,
    AssetSource,
    AssetType,
    CompatibilityLevel,
    DataCompleteness,
    FlexSignal,
    LocationType,
    MarketRule,
    MarketRuleClarity,
    OperationalComplexity,
    Portfolio,
    PriorityBand,
    RatingLevel,
    ServiceType,
    TemporalLevel,
)
from app.report_generator import generate_report

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_portfolio(**overrides) -> Portfolio:
    defaults = dict(
        portfolio_id="p1",
        portfolio_name="Test Portfolio",
        assets=[_make_asset_group()],
    )
    defaults.update(overrides)
    return Portfolio(**defaults)


def _make_asset_group(**overrides) -> AssetGroup:
    defaults = dict(
        source=AssetSource.synthetic,
        asset_type=AssetType.ev_charger,
        asset_count=1000,
        rated_power_kw=7.0,
        controllable_power_kw=4.5,
        availability_percent=0.03,
        response_reliability_percent=0.85,
        supported_service_types=[ServiceType.demand_turn_down],
        regional_distribution={},
    )
    defaults.update(overrides)
    return AssetGroup(**defaults)


def _make_signal(**overrides) -> FlexSignal:
    defaults = dict(
        signal_id="sig_test",
        dso="NGED",
        market_name="Test Market",
        area_name="Test Area",
        location_reference="ref",
        service_type=ServiceType.demand_turn_down,
        procurement_type="competitive",
    )
    defaults.update(overrides)
    return FlexSignal(**defaults)


def _make_rule(**overrides) -> MarketRule:
    defaults = dict(
        rule_id="rule_test",
        market_name="Test Market",
        buyer="Test Buyer",
        procurement_method="competitive",
        payment_type="utilisation",
        metering_requirements="half-hourly",
        baseline_requirements="required",
        stacking_notes="",
        participation_notes="",
        source_id="src_test",
        minimum_capacity_kw=50,
    )
    defaults.update(overrides)
    return MarketRule(**defaults)


# ---------------------------------------------------------------------------
# 1. Geography check
# ---------------------------------------------------------------------------

class TestCheckGeography:
    def test_neso_national_signal_with_presence(self):
        """NESO signal + any regional presence → partial."""
        asset = _make_asset_group(regional_distribution={"NGED": 0.5})
        portfolio = _make_portfolio(assets=[asset])
        signal = _make_signal(dso="NESO")
        level, evidence = _check_geography(portfolio, signal)
        assert level == RatingLevel.partial
        assert any("GB-wide" in e for e in evidence)

    def test_neso_national_signal_no_presence(self):
        """NESO signal + no regional data → unknown."""
        asset = _make_asset_group(regional_distribution={})
        portfolio = _make_portfolio(assets=[asset])
        signal = _make_signal(dso="NESO")
        level, evidence = _check_geography(portfolio, signal)
        assert level == RatingLevel.unknown

    def test_strong_dso_match(self):
        """DSO match with >20% distribution → strong."""
        asset = _make_asset_group(regional_distribution={"NGED": 0.5})
        portfolio = _make_portfolio(assets=[asset])
        signal = _make_signal(dso="NGED")
        level, evidence = _check_geography(portfolio, signal)
        assert level == RatingLevel.strong

    def test_partial_dso_match(self):
        """DSO match with <20% distribution → partial."""
        asset = _make_asset_group(regional_distribution={"NGED": 0.1})
        portfolio = _make_portfolio(assets=[asset])
        signal = _make_signal(dso="NGED")
        level, evidence = _check_geography(portfolio, signal)
        assert level == RatingLevel.partial

    def test_weak_dso_match(self):
        """No distribution for this DSO → weak."""
        asset = _make_asset_group(regional_distribution={"SPEN": 0.5})
        portfolio = _make_portfolio(assets=[asset])
        signal = _make_signal(dso="NGED")
        level, evidence = _check_geography(portfolio, signal)
        assert level == RatingLevel.weak

    def test_postcode_only_dso_evidence_is_unresolved(self):
        """Postcodes need verified geography before they can prove a DSO match."""
        asset = _make_asset_group(postcode_distribution={"B1": 1.0})
        portfolio = _make_portfolio(assets=[asset])

        level, evidence = _check_geography(portfolio, _make_signal(dso="NGED"))

        assert level == RatingLevel.unknown
        assert any("unresolved" in item.lower() for item in evidence)

    def test_postcode_only_neso_evidence_is_unresolved(self):
        """Postcodes alone do not yet prove GB-wide regional presence."""
        asset = _make_asset_group(postcode_distribution={"B1": 1.0})
        portfolio = _make_portfolio(assets=[asset])

        level, evidence = _check_geography(portfolio, _make_signal(dso="NESO"))

        assert level == RatingLevel.unknown
        assert any("unresolved" in item.lower() for item in evidence)


# ---------------------------------------------------------------------------
# 2. Asset compatibility
# ---------------------------------------------------------------------------

class TestCheckAssetCompatibility:
    def test_compatible(self):
        """Matching asset type + matching service → compatible."""
        asset = _make_asset_group(
            asset_type=AssetType.ev_charger,
            supported_service_types=[ServiceType.demand_turn_down],
        )
        portfolio = _make_portfolio(assets=[asset])
        signal = _make_signal(
            eligible_asset_types=[AssetType.ev_charger],
            service_type=ServiceType.demand_turn_down,
        )
        level, evidence = _check_asset_compatibility(portfolio, signal)
        assert level == CompatibilityLevel.compatible

    def test_partial_type_matches_but_service_unclear(self):
        """Matching asset type but service not listed → partial."""
        asset = _make_asset_group(
            asset_type=AssetType.ev_charger,
            supported_service_types=[ServiceType.generation_turn_up],
        )
        portfolio = _make_portfolio(assets=[asset])
        signal = _make_signal(
            eligible_asset_types=[AssetType.ev_charger],
            service_type=ServiceType.demand_turn_down,
        )
        level, evidence = _check_asset_compatibility(portfolio, signal)
        assert level == CompatibilityLevel.partial

    def test_partial_service_can_provide(self):
        """No matching type but can provide service → partial."""
        asset = _make_asset_group(
            asset_type=AssetType.battery,
            supported_service_types=[ServiceType.demand_turn_down],
        )
        portfolio = _make_portfolio(assets=[asset])
        signal = _make_signal(
            eligible_asset_types=[AssetType.ev_charger],
            service_type=ServiceType.demand_turn_down,
        )
        level, evidence = _check_asset_compatibility(portfolio, signal)
        assert level == CompatibilityLevel.partial

    def test_incompatible(self):
        """No matching type, no service match → incompatible."""
        asset = _make_asset_group(
            asset_type=AssetType.battery,
            supported_service_types=[ServiceType.generation_turn_up],
        )
        portfolio = _make_portfolio(assets=[asset])
        signal = _make_signal(
            eligible_asset_types=[AssetType.ev_charger],
            service_type=ServiceType.demand_turn_down,
        )
        level, evidence = _check_asset_compatibility(portfolio, signal)
        assert level == CompatibilityLevel.incompatible


# ---------------------------------------------------------------------------
# 3. Capacity check
# ---------------------------------------------------------------------------

class TestCheckCapacity:
    def test_strong(self):
        """Estimated kw >= signal capacity → strong."""
        asset = _make_asset_group(
            asset_count=10000, rated_power_kw=10.0, controllable_power_kw=10.0,
            availability_percent=0.5, response_reliability_percent=0.9,
        )
        portfolio = _make_portfolio(assets=[asset])
        signal = _make_signal(capacity_kw=100.0)
        level, evidence = _check_capacity(portfolio, signal)
        assert level == RatingLevel.strong

    def test_partial(self):
        """Estimated kw >= 50% of requirement → partial."""
        # 100 * 10 * 0.05 * 0.9 = 45 → 45/100 = 45% → weak
        # Need >= 50%: 100 * 10 * 0.06 * 0.9 = 54
        asset = _make_asset_group(
            asset_count=100, rated_power_kw=10.0, controllable_power_kw=10.0,
            availability_percent=0.06, response_reliability_percent=0.9,
        )
        portfolio = _make_portfolio(assets=[asset])
        signal = _make_signal(capacity_kw=100.0)
        level, evidence = _check_capacity(portfolio, signal)
        assert level == RatingLevel.partial

    def test_weak(self):
        """Estimated kw < 50% of requirement → weak."""
        asset = _make_asset_group(
            asset_count=10, controllable_power_kw=5.0,
            availability_percent=0.03, response_reliability_percent=0.85,
        )
        portfolio = _make_portfolio(assets=[asset])
        signal = _make_signal(capacity_kw=1000.0)
        level, evidence = _check_capacity(portfolio, signal)
        assert level == RatingLevel.weak

    def test_unknown_no_signal_capacity(self):
        """Signal with no capacity_kw → unknown."""
        portfolio = _make_portfolio(assets=[_make_asset_group()])
        signal = _make_signal(capacity_kw=None)
        level, evidence = _check_capacity(portfolio, signal)
        assert level == RatingLevel.unknown


# ---------------------------------------------------------------------------
# 4. Temporal check
# ---------------------------------------------------------------------------

class TestCheckTemporal:
    def test_plausible_ev_short_duration(self):
        """EV charger + short duration → plausible."""
        asset = _make_asset_group(asset_type=AssetType.ev_charger)
        portfolio = _make_portfolio(assets=[asset])
        signal = _make_signal(duration_minutes=60.0)
        level, evidence = _check_temporal(portfolio, signal)
        assert level == TemporalLevel.plausible

    def test_plausible_generator(self):
        """Generator + moderate duration → plausible."""
        asset = _make_asset_group(
            asset_type=AssetType.generator,
            supported_service_types=[ServiceType.generation_turn_up],
        )
        portfolio = _make_portfolio(assets=[asset])
        signal = _make_signal(duration_minutes=120.0)
        level, evidence = _check_temporal(portfolio, signal)
        assert level == TemporalLevel.plausible

    def test_uncertain_long_duration(self):
        """Very long duration → uncertain."""
        asset = _make_asset_group(asset_type=AssetType.ev_charger)
        portfolio = _make_portfolio(assets=[asset])
        signal = _make_signal(duration_minutes=300.0)
        level, evidence = _check_temporal(portfolio, signal)
        assert level == TemporalLevel.uncertain

    def test_unknown_no_timing_fields(self):
        """No timing fields at all → unknown."""
        portfolio = _make_portfolio(assets=[_make_asset_group()])
        signal = _make_signal(duration_minutes=None, window_start=None, lead_time=None)
        level, evidence = _check_temporal(portfolio, signal)
        assert level == TemporalLevel.unknown


# ---------------------------------------------------------------------------
# 5. Market rule clarity
# ---------------------------------------------------------------------------

class TestCheckMarketRule:
    def test_clear(self):
        """Rule with 3+ key fields → clear."""
        rule = _make_rule(
            minimum_capacity_kw=50, payment_type="utilisation",
            metering_requirements="hh", baseline_requirements="required",
        )
        signal = _make_signal(source_id="src_test")
        level, evidence = _check_market_rule(signal, [rule])
        assert level == MarketRuleClarity.clear

    def test_partial(self):
        """Rule with 2 key fields → partial."""
        rule = _make_rule(
            minimum_capacity_kw=50, payment_type="utilisation",
            metering_requirements="", baseline_requirements="",
        )
        signal = _make_signal(source_id="src_test")
        level, evidence = _check_market_rule(signal, [rule])
        assert level == MarketRuleClarity.partial

    def test_weak(self):
        """Rule with <2 key fields → weak."""
        rule = _make_rule(
            minimum_capacity_kw=0, payment_type="",
            metering_requirements="", baseline_requirements="",
        )
        signal = _make_signal(source_id="src_test")
        level, evidence = _check_market_rule(signal, [rule])
        assert level == MarketRuleClarity.weak

    def test_unknown_no_matching_rule(self):
        """No matching rule → unknown."""
        signal = _make_signal(source_id="no_match")
        level, evidence = _check_market_rule(signal, [])
        assert level == MarketRuleClarity.unknown


# ---------------------------------------------------------------------------
# 6. Data completeness
# ---------------------------------------------------------------------------

class TestCheckDataCompleteness:
    def test_high(self):
        """7+/8 fields present → high."""
        signal = _make_signal(
            location_type=LocationType.dso_region,
            capacity_kw=100.0,
            guide_price=18.0,
            duration_minutes=60.0,
            eligible_asset_types=[AssetType.ev_charger],
            source_id="src_test",
            source_updated_at="2026-01-01",
            raw_record={"record": "verified"},
        )
        level, evidence = _check_data_completeness(signal)
        assert level == DataCompleteness.high

    def test_medium(self):
        """4-5/8 fields present → medium."""
        signal = _make_signal(
            location_type=LocationType.unknown,
            capacity_kw=100.0,
            guide_price=None,
            payment_type="utilisation",
            duration_minutes=None,
            window_start=None,
            eligible_asset_types=[AssetType.ev_charger],
            source_id="src_test",
            source_updated_at=None,
            raw_record={"record": "verified"},
        )
        level, evidence = _check_data_completeness(signal)
        assert level == DataCompleteness.medium

    def test_low(self):
        """<4/8 fields present → low."""
        signal = _make_signal(
            location_type=LocationType.unknown,
            capacity_kw=None,
            guide_price=None,
            duration_minutes=None,
            window_start=None,
            eligible_asset_types=[],
            source_updated_at=None,
        )
        level, evidence = _check_data_completeness(signal)
        assert level == DataCompleteness.low

    def test_missing_source_identity_gates_completeness_to_low(self):
        signal = _make_signal(
            location_type=LocationType.dso_region,
            capacity_kw=100.0,
            guide_price=18.0,
            duration_minutes=60.0,
            eligible_asset_types=[AssetType.ev_charger],
            source_updated_at="2026-01-01",
            raw_record={"record": "verified"},
        )

        level, evidence = _check_data_completeness(signal)

        assert level == DataCompleteness.low
        assert any("source identity" in item.lower() for item in evidence)

    def test_missing_raw_record_gates_completeness_to_low(self):
        signal = _make_signal(
            location_type=LocationType.dso_region,
            capacity_kw=100.0,
            guide_price=18.0,
            duration_minutes=60.0,
            eligible_asset_types=[AssetType.ev_charger],
            source_updated_at="2026-01-01",
            source_id="src_test",
            raw_record=None,
        )

        level, evidence = _check_data_completeness(signal)

        assert level == DataCompleteness.low
        assert any("raw record" in item.lower() for item in evidence)


# ---------------------------------------------------------------------------
# 7. Priority band determination
# ---------------------------------------------------------------------------

class TestDeterminePriority:
    def test_high(self):
        """All checks good → high priority."""
        band = _determine_priority(
            geo=RatingLevel.strong,
            asset_compat=CompatibilityLevel.compatible,
            capacity=RatingLevel.strong,
            data_complete=DataCompleteness.high,
            market_clarity=MarketRuleClarity.clear,
            temporal=TemporalLevel.plausible,
            ops_complexity=OperationalComplexity.medium,
        )
        assert band == PriorityBand.high

    def test_medium(self):
        """Partial compat + some gaps → medium."""
        band = _determine_priority(
            geo=RatingLevel.partial,
            asset_compat=CompatibilityLevel.partial,
            capacity=RatingLevel.partial,
            data_complete=DataCompleteness.medium,
            market_clarity=MarketRuleClarity.partial,
            temporal=TemporalLevel.plausible,
            ops_complexity=OperationalComplexity.medium,
        )
        assert band == PriorityBand.medium

    def test_low_weak_geo(self):
        """Weak geography → low."""
        band = _determine_priority(
            geo=RatingLevel.weak,
            asset_compat=CompatibilityLevel.compatible,
            capacity=RatingLevel.strong,
            data_complete=DataCompleteness.high,
            market_clarity=MarketRuleClarity.clear,
            temporal=TemporalLevel.plausible,
            ops_complexity=OperationalComplexity.medium,
        )
        assert band == PriorityBand.low

    def test_low_incompatible_assets(self):
        """Incompatible assets → low."""
        band = _determine_priority(
            geo=RatingLevel.strong,
            asset_compat=CompatibilityLevel.incompatible,
            capacity=RatingLevel.strong,
            data_complete=DataCompleteness.high,
            market_clarity=MarketRuleClarity.clear,
            temporal=TemporalLevel.plausible,
            ops_complexity=OperationalComplexity.medium,
        )
        assert band == PriorityBand.low

    def test_insufficient_evidence_two_unknowns(self):
        """Two unknowns in geo/capacity/temporal → insufficient_evidence."""
        band = _determine_priority(
            geo=RatingLevel.unknown,
            asset_compat=CompatibilityLevel.compatible,
            capacity=RatingLevel.unknown,
            data_complete=DataCompleteness.medium,
            market_clarity=MarketRuleClarity.clear,
            temporal=TemporalLevel.plausible,
            ops_complexity=OperationalComplexity.medium,
        )
        assert band == PriorityBand.insufficient_evidence

    def test_insufficient_evidence_low_data_and_no_rule(self):
        """Low data completeness + unknown rule → insufficient_evidence."""
        band = _determine_priority(
            geo=RatingLevel.partial,
            asset_compat=CompatibilityLevel.compatible,
            capacity=RatingLevel.partial,
            data_complete=DataCompleteness.low,
            market_clarity=MarketRuleClarity.unknown,
            temporal=TemporalLevel.plausible,
            ops_complexity=OperationalComplexity.medium,
        )
        assert band == PriorityBand.insufficient_evidence


def test_missing_service_evidence_is_unclear_not_incompatible() -> None:
    signal = _make_signal(service_type=None)
    level, _ = _check_asset_compatibility(_make_portfolio(), signal)
    assert level == CompatibilityLevel.unclear


def test_missing_eligibility_evidence_is_unclear_not_incompatible() -> None:
    signal = _make_signal(eligible_asset_types=None)
    level, _ = _check_asset_compatibility(_make_portfolio(), signal)
    assert level == CompatibilityLevel.unclear


def test_missing_region_evidence_is_unknown_not_weak() -> None:
    portfolio = _make_portfolio(
        assets=[_make_asset_group(regional_distribution={})]
    )
    level, _ = _check_geography(portfolio, _make_signal(dso="NGED"))
    assert level == RatingLevel.unknown


def test_unprovenanced_signal_cannot_match_blank_source_rule() -> None:
    portfolio = _make_portfolio(
        assets=[_make_asset_group(regional_distribution={"NGED": 0.5})]
    )
    signal = _make_signal(
        location_type=LocationType.dso_region,
        capacity_kw=100.0,
        guide_price=18.0,
        duration_minutes=60.0,
        eligible_asset_types=[AssetType.ev_charger],
        source_updated_at="2026-01-01",
        source_id=None,
        source_dataset_id=None,
        raw_record=None,
    )
    blank_source_rule = _make_rule().model_copy(update={"source_id": ""})

    assessment = assess_portfolio(portfolio, [signal], [blank_source_rule])[0]

    assert assessment.market_rule_clarity == MarketRuleClarity.unknown
    assert assessment.operational_complexity == OperationalComplexity.unknown
    assert assessment.data_completeness == DataCompleteness.low
    assert (
        assessment.investigation_priority_band
        == PriorityBand.insufficient_evidence
    )


def test_provenanced_signal_preserves_legitimate_rule_match() -> None:
    portfolio = _make_portfolio(
        assets=[_make_asset_group(regional_distribution={"NGED": 0.5})]
    )
    signal = _make_signal(
        location_type=LocationType.dso_region,
        capacity_kw=100.0,
        guide_price=18.0,
        duration_minutes=60.0,
        eligible_asset_types=[AssetType.ev_charger],
        source_updated_at="2026-01-01",
        source_dataset_id="src_test",
        raw_record={"record": "verified"},
    )

    assessment = assess_portfolio(portfolio, [signal], [_make_rule()])[0]

    assert assessment.market_rule_clarity == MarketRuleClarity.clear
    assert assessment.operational_complexity == OperationalComplexity.medium
    assert assessment.data_completeness == DataCompleteness.high
    assert assessment.investigation_priority_band == PriorityBand.high


def test_assess_portfolio_handles_all_nullable_signal_evidence() -> None:
    signal = _make_signal(
        service_type=None,
        market_name=None,
        area_name=None,
        location_type=None,
        location_reference=None,
        requirement_type=None,
        procurement_type=None,
        eligible_asset_types=None,
        platform=None,
    )
    assessment = assess_portfolio(_make_portfolio(), [signal], [])[0]
    assert assessment.asset_type_compatibility == CompatibilityLevel.unclear
    assert "None" not in "\n".join(
        assessment.evidence_summary + assessment.next_steps
    )


def test_report_renders_nullable_signal_evidence_as_unknown() -> None:
    portfolio = _make_portfolio()
    signal = _make_signal(
        service_type=None,
        market_name=None,
        area_name=None,
        location_type=None,
        location_reference=None,
        requirement_type=None,
        procurement_type=None,
        eligible_asset_types=None,
        platform=None,
    )
    assessment = assess_portfolio(portfolio, [signal], [])[0]

    report = generate_report(portfolio, [assessment], [signal], [])

    assert "Unknown" in report
    assert "None" not in report


def test_assessment_disclaimer_does_not_invent_signal_provenance() -> None:
    signal = _make_signal(
        confidence_level="unknown",
        source_id=None,
        source_dataset_id=None,
        raw_record=None,
    )

    assessment = assess_portfolio(_make_portfolio(), [signal], [])[0]

    assert "curated public-source data" not in assessment.disclaimer
    assert "supplied signal and portfolio evidence" in assessment.disclaimer
    assert "may be missing or unverified" in assessment.disclaimer
    assert "not a bid recommendation" in assessment.disclaimer
    assert "eligibility confirmation" in assessment.disclaimer
    assert "revenue forecast" in assessment.disclaimer
    assert "commercial decisioning tool" in assessment.disclaimer
    assert signal.source_id is None
    assert signal.source_dataset_id is None
    assert signal.raw_record is None

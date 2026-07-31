"""Heuristic matching logic — 7 checks + priority band determination."""

from __future__ import annotations

from .models import (
    AssetGroup,
    AssetType,
    CompatibilityLevel,
    DataCompleteness,
    FitAssessment,
    FlexSignal,
    MarketRule,
    MarketRuleClarity,
    OperationalComplexity,
    Portfolio,
    PriorityBand,
    RatingLevel,
    ServiceType,
    TemporalLevel,
)


def _estimate_available_kw(group: AssetGroup) -> float:
    """asset_count × controllable_power_kw × availability × reliability."""
    return (
        group.asset_count
        * group.controllable_power_kw
        * group.availability_percent
        * group.response_reliability_percent
    )


def _total_estimated_kw(portfolio: Portfolio) -> float:
    return sum(_estimate_available_kw(g) for g in portfolio.assets)


# ---------------------------------------------------------------------------
# 1. Geography check
# ---------------------------------------------------------------------------

def _check_geography(portfolio: Portfolio, signal: FlexSignal) -> tuple[RatingLevel, list[str]]:
    evidence: list[str] = []
    dso = signal.dso.upper()
    has_location_evidence = any(
        group.regional_distribution or group.postcode_distribution
        for group in portfolio.assets
    )
    if not has_location_evidence:
        evidence.append("No regional or postcode distribution data found for portfolio.")
        return RatingLevel.unknown, evidence

    if dso == "NESO":
        # National signal — partial if any regional presence
        has_presence = any(
            g.regional_distribution.get(dso, 0) > 0 for g in portfolio.assets
        )
        if not has_presence:
            has_presence = any(
                any(v > 0 for v in g.regional_distribution.values())
                for g in portfolio.assets
            )
        if has_presence:
            evidence.append("Portfolio has GB-wide regional presence relevant to national NESO signal.")
            return RatingLevel.partial, evidence
        evidence.append("No regional distribution data found for portfolio.")
        return RatingLevel.unknown, evidence

    # DSO-specific signal
    max_share = max(
        (g.regional_distribution.get(dso, 0) for g in portfolio.assets), default=0
    )
    if max_share > 0.2:
        evidence.append(f"Portfolio has {max_share:.0%} regional distribution in {dso}.")
        return RatingLevel.strong, evidence
    elif max_share > 0:
        evidence.append(f"Portfolio has {max_share:.0%} regional distribution in {dso} — partial presence.")
        return RatingLevel.partial, evidence
    else:
        evidence.append(f"Portfolio has no regional distribution in {dso}.")
        return RatingLevel.weak, evidence


# ---------------------------------------------------------------------------
# 2. Asset-type compatibility
# ---------------------------------------------------------------------------

def _check_asset_compatibility(
    portfolio: Portfolio, signal: FlexSignal
) -> tuple[CompatibilityLevel, list[str]]:
    evidence: list[str] = []
    if signal.service_type is None:
        evidence.append("Signal does not identify a service type.")
        return CompatibilityLevel.unclear, evidence
    if signal.eligible_asset_types is None:
        evidence.append("Signal does not provide eligible asset type evidence.")
        return CompatibilityLevel.unclear, evidence

    signal_assets = set(signal.eligible_asset_types)
    portfolio_types = {g.asset_type for g in portfolio.assets}

    matching = signal_assets & portfolio_types
    if not matching:
        # Check if any portfolio asset supports the signal service type
        svc = signal.service_type
        can_provide = any(
            svc in g.supported_service_types for g in portfolio.assets
        )
        if can_provide:
            evidence.append("Portfolio assets can provide the service type but are not listed as eligible asset types.")
            return CompatibilityLevel.partial, evidence
        evidence.append("No portfolio asset types match signal eligibility or service capability.")
        return CompatibilityLevel.incompatible, evidence

    # Check if matching assets also support the service type
    svc_compatible = any(
        g.asset_type in matching and signal.service_type in g.supported_service_types
        for g in portfolio.assets
    )
    if svc_compatible:
        types_str = ", ".join(sorted(t.value for t in matching))
        evidence.append(f"Portfolio asset types [{types_str}] are eligible and support {signal.service_type.value}.")
        return CompatibilityLevel.compatible, evidence
    else:
        types_str = ", ".join(sorted(t.value for t in matching))
        evidence.append(f"Asset types [{types_str}] are eligible but service type support is unclear.")
        return CompatibilityLevel.partial, evidence


# ---------------------------------------------------------------------------
# 3. Capacity plausibility
# ---------------------------------------------------------------------------

def _check_capacity(
    portfolio: Portfolio, signal: FlexSignal
) -> tuple[RatingLevel, list[str]]:
    evidence: list[str] = []
    est_kw = _total_estimated_kw(portfolio)
    sig_cap = signal.capacity_kw

    if sig_cap is None:
        evidence.append("Signal does not specify capacity requirement.")
        return RatingLevel.unknown, evidence

    if est_kw >= sig_cap:
        evidence.append(f"Estimated available {est_kw:.1f} kW >= signal requirement {sig_cap:.0f} kW.")
        return RatingLevel.strong, evidence
    elif est_kw >= sig_cap * 0.5:
        evidence.append(f"Estimated available {est_kw:.1f} kW is {est_kw / sig_cap:.0%} of signal requirement {sig_cap:.0f} kW.")
        return RatingLevel.partial, evidence
    else:
        evidence.append(f"Estimated available {est_kw:.1f} kW is only {est_kw / sig_cap:.0%} of signal requirement {sig_cap:.0f} kW.")
        return RatingLevel.weak, evidence


# ---------------------------------------------------------------------------
# 4. Temporal feasibility
# ---------------------------------------------------------------------------

def _check_temporal(
    portfolio: Portfolio, signal: FlexSignal
) -> tuple[TemporalLevel, list[str]]:
    evidence: list[str] = []
    if signal.duration_minutes is None and signal.window_start is None and signal.lead_time is None:
        evidence.append("Signal has no timing fields specified.")
        return TemporalLevel.unknown, evidence

    # Simple heuristic: EV chargers and batteries generally handle 30-180 min
    duration = signal.duration_minutes or 0
    has_flexible_assets = any(
        g.asset_type in (AssetType.ev_charger, AssetType.battery) for g in portfolio.assets
    )
    has_generators = any(g.asset_type == AssetType.generator for g in portfolio.assets)

    if duration > 0:
        if has_flexible_assets and duration <= 180:
            evidence.append(f"Duration {duration:.0f} min is within typical EV/battery flexibility window.")
            return TemporalLevel.plausible, evidence
        elif has_generators and duration <= 240:
            evidence.append(f"Duration {duration:.0f} min is achievable for generators.")
            return TemporalLevel.plausible, evidence
        elif duration > 240:
            evidence.append(f"Duration {duration:.0f} min may be challenging for most DER assets.")
            return TemporalLevel.uncertain, evidence

    evidence.append("Timing data exists but asset-level feasibility is uncertain without detailed scheduling.")
    return TemporalLevel.uncertain, evidence


# ---------------------------------------------------------------------------
# 5. Market-rule clarity
# ---------------------------------------------------------------------------

def _check_market_rule(
    signal: FlexSignal, rules: list[MarketRule]
) -> tuple[MarketRuleClarity, list[str]]:
    evidence: list[str] = []
    sid = signal.source_id or signal.source_dataset_id or ""
    matching_rules = [r for r in rules if r.source_id == sid]

    if not matching_rules:
        evidence.append("No matching market rule found for this signal source.")
        return MarketRuleClarity.unknown, evidence

    rule = matching_rules[0]
    has_fields = [
        rule.minimum_capacity_kw is not None,
        bool(rule.payment_type),
        bool(rule.metering_requirements),
        bool(rule.baseline_requirements),
    ]
    present = sum(has_fields)

    if present >= 3:
        evidence.append(f"Market rule '{rule.market_name}' provides capacity, payment, metering, and baseline details.")
        return MarketRuleClarity.clear, evidence
    elif present >= 2:
        evidence.append(f"Market rule '{rule.market_name}' has some participation details but gaps remain.")
        return MarketRuleClarity.partial, evidence
    else:
        evidence.append(f"Market rule '{rule.market_name}' has limited detail.")
        return MarketRuleClarity.weak, evidence


# ---------------------------------------------------------------------------
# 6. Data completeness
# ---------------------------------------------------------------------------

def _check_data_completeness(signal: FlexSignal) -> tuple[DataCompleteness, list[str]]:
    evidence: list[str] = []
    fields_present = 0
    total = 8

    checks = [
        ("DSO", bool(signal.dso)),
        ("service type", bool(signal.service_type)),
        (
            "location",
            signal.location_type is not None
            and signal.location_type.value != "unknown",
        ),
        ("capacity", signal.capacity_kw is not None),
        ("price/payment", signal.guide_price is not None or signal.payment_type is not None),
        ("timing", signal.duration_minutes is not None or signal.window_start is not None),
        ("eligible asset types", bool(signal.eligible_asset_types)),
        ("source update date", signal.source_updated_at is not None),
    ]

    for name, present in checks:
        if present:
            fields_present += 1

    ratio = fields_present / total
    if ratio >= 0.75:
        evidence.append(f"{fields_present}/{total} key fields present — good data quality.")
        return DataCompleteness.high, evidence
    elif ratio >= 0.5:
        evidence.append(f"{fields_present}/{total} key fields present — some gaps.")
        return DataCompleteness.medium, evidence
    else:
        evidence.append(f"{fields_present}/{total} key fields present — significant gaps.")
        return DataCompleteness.low, evidence


# ---------------------------------------------------------------------------
# 7. Operational complexity
# ---------------------------------------------------------------------------

def _check_operational_complexity(
    portfolio: Portfolio, signal: FlexSignal, rule: MarketRule | None
) -> tuple[OperationalComplexity, list[str]]:
    evidence: list[str] = []
    asset_types = {g.asset_type for g in portfolio.assets}
    svc = signal.service_type

    # Baseline complexity by asset + service
    base = "medium"
    if asset_types == {AssetType.ev_charger} and svc in (ServiceType.demand_turn_down, ServiceType.demand_turn_up):
        base = "medium"
        evidence.append("EV charger flexibility: medium complexity (user override risk, session dependency).")
    elif AssetType.battery in asset_types:
        base = "medium"
        evidence.append("Battery flexibility: medium complexity (SoC management, import/export metering).")
    elif AssetType.generator in asset_types:
        base = "high"
        evidence.append("Generator flexibility: higher complexity (fuel, emissions, ramp constraints).")

    # Escalate if metering/baseline unclear
    if rule is None:
        evidence.append("No market rule found — cannot assess metering/baseline requirements.")
        return OperationalComplexity.unknown, evidence

    if "not validated" in (portfolio.assets[0].metering_assumption.lower() if portfolio.assets else ""):
        if base == "medium":
            evidence.append("Metering not validated — increases operational complexity.")
            return OperationalComplexity.high, evidence

    if base == "high":
        return OperationalComplexity.high, evidence
    return OperationalComplexity.medium, evidence


# ---------------------------------------------------------------------------
# Investigation priority band
# ---------------------------------------------------------------------------

def _determine_priority(
    geo: RatingLevel,
    asset_compat: CompatibilityLevel,
    capacity: RatingLevel,
    data_complete: DataCompleteness,
    market_clarity: MarketRuleClarity,
    temporal: TemporalLevel,
    ops_complexity: OperationalComplexity,
) -> PriorityBand:
    # Hard blockers
    if asset_compat == CompatibilityLevel.incompatible:
        return PriorityBand.low
    if geo == RatingLevel.weak:
        return PriorityBand.low

    # Insufficient evidence
    unknowns = 0
    if geo == RatingLevel.unknown:
        unknowns += 1
    if capacity == RatingLevel.unknown:
        unknowns += 1
    if temporal == TemporalLevel.unknown:
        unknowns += 1
    if unknowns >= 2:
        return PriorityBand.insufficient_evidence
    if data_complete == DataCompleteness.low and market_clarity in (MarketRuleClarity.unknown, MarketRuleClarity.weak):
        return PriorityBand.insufficient_evidence

    # High priority
    if (
        geo in (RatingLevel.strong, RatingLevel.partial)
        and asset_compat == CompatibilityLevel.compatible
        and capacity in (RatingLevel.strong, RatingLevel.partial)
        and data_complete in (DataCompleteness.high, DataCompleteness.medium)
        and market_clarity in (MarketRuleClarity.clear, MarketRuleClarity.partial)
    ):
        return PriorityBand.high

    # Medium priority
    if (
        asset_compat in (CompatibilityLevel.compatible, CompatibilityLevel.partial)
        and capacity in (RatingLevel.strong, RatingLevel.partial, RatingLevel.unknown)
        and data_complete != DataCompleteness.low
    ):
        return PriorityBand.medium

    # Low priority (weak evidence)
    return PriorityBand.low


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def assess_portfolio(
    portfolio: Portfolio,
    signals: list[FlexSignal],
    rules: list[MarketRule],
) -> list[FitAssessment]:
    """Run all 7 checks for every signal and return ranked assessments."""
    assessments: list[FitAssessment] = []
    est_kw = _total_estimated_kw(portfolio)

    for signal in signals:
        geo_level, geo_ev = _check_geography(portfolio, signal)
        asset_level, asset_ev = _check_asset_compatibility(portfolio, signal)
        cap_level, cap_ev = _check_capacity(portfolio, signal)
        temp_level, temp_ev = _check_temporal(portfolio, signal)
        rule_level, rule_ev = _check_market_rule(signal, rules)
        dc_level, dc_ev = _check_data_completeness(signal)

        sid = signal.source_id or signal.source_dataset_id or ""
        matching_rules = [r for r in rules if r.source_id == sid]
        rule_obj = matching_rules[0] if matching_rules else None
        ops_level, ops_ev = _check_operational_complexity(portfolio, signal, rule_obj)

        band = _determine_priority(
            geo_level, asset_level, cap_level, dc_level, rule_level, temp_level, ops_level
        )

        evidence = geo_ev + asset_ev + cap_ev + temp_ev + rule_ev + dc_ev + ops_ev

        missing: list[str] = []
        if cap_level == RatingLevel.unknown:
            missing.append("Signal capacity requirement not specified.")
        if temp_level == TemporalLevel.unknown:
            missing.append("Timing/duration details missing from signal.")
        if rule_level == MarketRuleClarity.unknown:
            missing.append("No market rule context available for this source.")
        if not signal.guide_price:
            missing.append("No pricing/payment information available.")
        if portfolio.assets and not portfolio.assets[0].postcode_distribution:
            missing.append("Postcode-level location data not available for portfolio or signal.")

        risks: list[str] = []
        if asset_level == CompatibilityLevel.partial:
            risks.append("Asset type eligibility is partial — may require additional qualification.")
        if cap_level == RatingLevel.weak:
            risks.append("Estimated capacity is well below signal requirement.")
        if ops_level == OperationalComplexity.high:
            risks.append("High operational complexity — baselining and metering need validation.")
        for g in portfolio.assets:
            for note in g.operational_notes:
                if "risk" in note.lower():
                    risks.append(note)
        if signal.confidence_level.value in ("low", "unknown"):
            risks.append(f"Signal confidence level is {signal.confidence_level.value}.")

        next_steps: list[str] = []
        if band in (PriorityBand.high, PriorityBand.medium):
            area_name = signal.area_name or "Unknown area"
            next_steps.append(
                f"Investigate {signal.dso} procurement process for {area_name}."
            )
            if not signal.guide_price:
                next_steps.append("Request indicative pricing from DSO.")
            next_steps.append("Validate metering and baseline requirements against current capabilities.")
        if band == PriorityBand.low:
            next_steps.append("Monitor signal — revisit if portfolio composition changes.")
        if band == PriorityBand.insufficient_evidence:
            next_steps.append("Gather more data on this signal before assessing fit.")

        disclaimer = (
            "This assessment uses curated public-source data and transparent heuristic "
            "assumptions. It is not a bid recommendation, eligibility confirmation, "
            "revenue forecast, or commercial decisioning tool."
        )

        assessments.append(
            FitAssessment(
                assessment_id=f"assess_{signal.signal_id}_{portfolio.portfolio_id}",
                portfolio_id=portfolio.portfolio_id,
                signal_id=signal.signal_id,
                estimated_available_kw=round(est_kw, 2),
                investigation_priority_band=band,
                location_evidence=geo_level,
                asset_type_compatibility=asset_level,
                capacity_plausibility=cap_level,
                temporal_feasibility=temp_level,
                market_rule_clarity=rule_level,
                data_completeness=dc_level,
                operational_complexity=ops_level,
                evidence_summary=evidence,
                missing_information=missing,
                risk_flags=risks,
                next_steps=next_steps,
                disclaimer=disclaimer,
            )
        )

    # Sort: high > medium > low > insufficient
    band_order = {
        PriorityBand.high: 0,
        PriorityBand.medium: 1,
        PriorityBand.low: 2,
        PriorityBand.insufficient_evidence: 3,
    }
    assessments.sort(key=lambda a: band_order[a.investigation_priority_band])
    return assessments

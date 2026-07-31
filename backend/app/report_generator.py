"""Generate a Markdown Flexibility Fit Report."""

from __future__ import annotations

from .models import (
    DataSource,
    FitAssessment,
    FlexSignal,
    Portfolio,
    PriorityBand,
)

BAND_LABELS = {
    PriorityBand.high: "🔴 High",
    PriorityBand.medium: "🟡 Medium",
    PriorityBand.low: "🟢 Low",
    PriorityBand.insufficient_evidence: "⚪ Insufficient Evidence",
}


def generate_report(
    portfolio: Portfolio,
    assessments: list[FitAssessment],
    signals: list[FlexSignal],
    sources: list[DataSource],
) -> str:
    """Return a full Markdown report."""
    signal_map = {s.signal_id: s for s in signals}

    top = assessments[:5]
    others = assessments[5:]

    lines: list[str] = []
    _add = lines.append

    # ── Title ──
    _add("# Synthetic Flexibility Fit Demonstration\n")
    _add(
        "> Synthetic demonstration — no live or current portal data is used.\n"
    )

    # ── 1. Portfolio Summary ──
    _add("## 1. Portfolio Summary\n")
    _add(f"**Portfolio:** {portfolio.portfolio_name}")
    _add(f"**Portfolio ID:** `{portfolio.portfolio_id}`\n")

    total_rated = sum(g.rated_power_kw * g.asset_count for g in portfolio.assets)
    total_controllable = sum(g.controllable_power_kw * g.asset_count for g in portfolio.assets)
    total_est = sum(
        g.asset_count * g.controllable_power_kw * g.availability_percent * g.response_reliability_percent
        for g in portfolio.assets
    )

    _add("| Asset Type | Count | Rated kW | Controllable kW | Availability | Reliability | Est. Flex kW |")
    _add("|---|---:|---:|---:|---:|---:|---:|")
    for g in portfolio.assets:
        est = g.asset_count * g.controllable_power_kw * g.availability_percent * g.response_reliability_percent
        _add(
            f"| {g.asset_type.value} | {g.asset_count:,} | {g.rated_power_kw:,.1f} | "
            f"{g.controllable_power_kw:,.1f} | {g.availability_percent:.0%} | "
            f"{g.response_reliability_percent:.0%} | {est:,.2f} |"
        )
    _add(
        f"| **Total** | | **{total_rated:,.0f}** | **{total_controllable:,.0f}** | | | **{total_est:,.2f}** |\n"
    )

    _add("**Regional Distribution:**")
    for g in portfolio.assets:
        regions = ", ".join(f"{k}: {v:.0%}" for k, v in g.regional_distribution.items() if v > 0)
        _add(f"- {g.asset_type.value}: {regions}")
    _add("")

    for g in portfolio.assets:
        if g.baseline_assumption:
            _add(f"**Baseline ({g.asset_type.value}):** {g.baseline_assumption}")
        if g.metering_assumption:
            _add(f"**Metering ({g.asset_type.value}):** {g.metering_assumption}")
    _add("")

    # ── 2. Source Data Summary ──
    _add("## 2. Source Data Summary\n")
    dsos_represented = sorted({s.dso for s in signals})
    _add(f"- **Signals considered:** {len(signals)}")
    _add(f"- **Sources represented:** {len(sources)}")
    _add(f"- **DSOs represented:** {', '.join(dsos_represented)}")
    curated_count = sum(1 for s in sources if s.live_or_curated.value == "curated")
    _add(f"- **Data status:** {curated_count}/{len(sources)} curated, 0 live\n")

    if sources:
        _add("**Key Source Limitations:**")
        for src in sources:
            if src.limitations:
                _add(f"- **{src.source_name}:** {src.limitations[0]}")
        _add("")

    # ── 3. Top Investigation Matches ──
    _add("## 3. Top Investigation Matches\n")

    if not top:
        _add("_No matches found._\n")
    else:
        for i, assess in enumerate(top, 1):
            sig = signal_map.get(assess.signal_id)
            if not sig:
                continue
            market_name = sig.market_name or "Unknown market"
            area_name = sig.area_name or "Unknown area"
            location_type = (
                sig.location_type.value if sig.location_type else "Unknown"
            )
            service_type = (
                sig.service_type.value.replace("_", " ").title()
                if sig.service_type
                else "Unknown"
            )
            procurement_type = sig.procurement_type or "Unknown"
            _add(f"### {i}. {market_name} — {area_name}\n")

            _add("#### Signal Summary\n")
            _add(f"- **DSO:** {sig.dso}")
            _add(f"- **Area:** {area_name} ({location_type})")
            _add(f"- **Service Type:** {service_type}")
            _add(f"- **Procurement:** {procurement_type}")
            if sig.capacity_kw:
                _add(f"- **Capacity Required:** {sig.capacity_kw:,.0f} kW")
            if sig.duration_minutes:
                _add(f"- **Duration:** {sig.duration_minutes:.0f} minutes")
            if sig.lead_time:
                _add(f"- **Lead Time:** {sig.lead_time}")
            if sig.guide_price and sig.price_unit:
                _add(f"- **Guide Price:** £{sig.guide_price} {sig.price_unit}")
            if sig.utilisation_estimate:
                _add(f"- **Utilisation Estimate:** {sig.utilisation_estimate}")
            _add(f"- **Confidence:** {sig.confidence_level.value}")
            _add("")

            _add("#### Matching Analysis\n")
            _add(f"- **Geography Check:** {assess.location_evidence.value}")
            _add(f"- **Asset Type Check:** {assess.asset_type_compatibility.value}")
            _add(f"- **Capacity Check:** {assess.capacity_plausibility.value}")
            _add(f"- **Temporal Check:** {assess.temporal_feasibility.value}")
            _add(f"- **Market Rule Check:** {assess.market_rule_clarity.value}")
            _add(f"- **Data Completeness:** {assess.data_completeness.value}")
            _add(f"- **Operational Complexity:** {assess.operational_complexity.value}")
            _add("")

            _add("#### Investigation Priority\n")
            _add(f"**{BAND_LABELS[assess.investigation_priority_band]}**")
            _add(f"- Estimated Available Capacity: **{assess.estimated_available_kw:,.2f} kW**\n")

            _add("#### Evidence")
            for e in assess.evidence_summary:
                _add(f"- {e}")
            _add("")

            if assess.missing_information:
                _add("#### Missing Information")
                for m in assess.missing_information:
                    _add(f"- {m}")
                _add("")

            if assess.risk_flags:
                _add("#### Risks")
                for r in assess.risk_flags:
                    _add(f"- {r}")
                _add("")

            if assess.next_steps:
                _add("#### Suggested Next Steps")
                for ns in assess.next_steps:
                    _add(f"- {ns}")
                _add("")

            _add("---\n")

    # ── 4. DSO Summary ──
    _add("## 4. DSO Summary\n")
    dso_groups: dict[str, list[FitAssessment]] = {}
    for a in assessments:
        sig = signal_map.get(a.signal_id)
        if sig:
            dso_groups.setdefault(sig.dso, []).append(a)

    for dso, dso_assessments in sorted(dso_groups.items()):
        band_counts: dict[str, int] = {}
        for a in dso_assessments:
            label = a.investigation_priority_band.value
            band_counts[label] = band_counts.get(label, 0) + 1
        summary = ", ".join(f"{count} {band}" for band, count in band_counts.items())
        _add(f"- **{dso}:** {len(dso_assessments)} signal(s) — {summary}")
    _add("")

    # ── 5. Other Signals Considered ──
    if others:
        _add("## 5. Other Signals Considered\n")
        _add("| Signal | DSO | Area | Service | Priority |")
        _add("|---|---|---|---|---|")
        for a in others:
            sig = signal_map.get(a.signal_id)
            if sig:
                area_name = sig.area_name or "Unknown"
                service_type = (
                    sig.service_type.value if sig.service_type else "Unknown"
                )
                _add(
                    f"| {sig.signal_id} | {sig.dso} | {area_name} | "
                    f"{service_type} | {a.investigation_priority_band.value} |"
                )
        _add("")

    # ── 6. Disclaimer ──
    _add("## 6. Disclaimer\n")
    _add(
        "This synthetic-only report is generated solely from the submitted "
        "demonstration portfolio. No portal-derived signals, sources, market "
        "evidence, or procurement records are used. "
        "It is **not** a bid recommendation, eligibility confirmation, revenue forecast, "
        "regulatory opinion, or commercial decisioning tool. All estimates are directional "
        "and should be validated against official DSO procurement documentation before "
        "taking any commercial action.\n"
    )

    return "\n".join(lines)

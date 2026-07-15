"""Confidence level rubric for FlexCompass.

Single scored function that determines confidence based on:
  - Geography match quality (polygon > prefix > district-only)
  - Key field completeness
  - Data source reliability

Rubric from the brief:
  high                  = full-postcode polygon match + all key fields present
  medium                = prefix/district match + most key fields present
  low                   = district-only or missing key fields
  insufficient_evidence = too few fields to make a directional assessment
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from .config import config
from .models import ConfidenceLevel


class GeographyMatch(IntEnum):
    """Quality of the geographic match between asset and zone."""
    POLYGON = 4       # Full point-in-polygon (highest quality)
    FULL_POSTCODE = 3 # Exact postcode match against zone postcode list
    PREFIX = 2        # Postcode prefix/district match
    DISTRICT = 1      # District-level only
    NONE = 0          # No geographic match


@dataclass
class ConfidenceInput:
    """Inputs to the confidence scoring function."""
    geography_match: GeographyMatch
    fields_present: int       # count of key fields with data
    fields_total: int         # total key fields checked
    has_capacity: bool        # capacity_kw is not None
    has_price: bool           # guide_price or payment_type present
    has_timing: bool          # window/duration/lead_time present
    has_eligible_assets: bool # eligible_asset_types is non-empty
    source_reliability: float = 1.0  # 0.0-1.0 multiplier (default: trust the source)


# Key fields the rubric checks
KEY_FIELDS = [
    "dso",
    "service_type",
    "location",
    "capacity",
    "price_or_payment",
    "timing",
    "eligible_asset_types",
    "source_updated_at",
]


def score_confidence(inp: ConfidenceInput) -> tuple[ConfidenceLevel, float, list[str]]:
    """Score confidence from structured inputs.

    Returns:
        (confidence_level, numeric_score 0.0-1.0, reasons)
    """
    reasons: list[str] = []
    score = 0.0

    # --- Geography component (40% weight) ---
    geo_weight = 0.40
    geo_score = inp.geography_match / GeographyMatch.POLYGON  # 0.0-1.0
    score += geo_score * geo_weight

    if inp.geography_match == GeographyMatch.POLYGON:
        reasons.append("Full polygon geometry available for zone matching.")
    elif inp.geography_match == GeographyMatch.FULL_POSTCODE:
        reasons.append("Exact postcode match against zone postcode list.")
    elif inp.geography_match == GeographyMatch.PREFIX:
        reasons.append("Postcode prefix match only — confidence downgraded.")
    elif inp.geography_match == GeographyMatch.DISTRICT:
        reasons.append("District-level match only — coarse geographic fit.")
    else:
        reasons.append("No geographic match available.")

    # --- Field completeness component (40% weight) ---
    field_weight = 0.40
    if inp.fields_total > 0:
        field_ratio = inp.fields_present / inp.fields_total
    else:
        field_ratio = 0.0
    score += field_ratio * field_weight

    reasons.append(
        f"{inp.fields_present}/{inp.fields_total} key fields present."
    )

    # --- Critical fields bonus (20% weight) ---
    critical_weight = 0.20
    critical_present = sum([
        inp.has_capacity,
        inp.has_price,
        inp.has_timing,
        inp.has_eligible_assets,
    ])
    critical_score = critical_present / 4.0
    score += critical_score * critical_weight

    missing_critical = []
    if not inp.has_capacity:
        missing_critical.append("capacity")
    if not inp.has_price:
        missing_critical.append("price/payment")
    if not inp.has_timing:
        missing_critical.append("timing")
    if not inp.has_eligible_assets:
        missing_critical.append("eligible asset types")
    if missing_critical:
        reasons.append(f"Missing critical fields: {', '.join(missing_critical)}.")

    # --- Source reliability modifier ---
    score *= inp.source_reliability

    # --- Determine level from score ---
    if inp.fields_present < config.confidence_min_fields_for_low:
        level = ConfidenceLevel.insufficient_evidence
        reasons.append("Insufficient fields for any directional assessment.")
    elif inp.geography_match >= GeographyMatch.FULL_POSTCODE and field_ratio >= 0.75:
        level = ConfidenceLevel.high
    elif inp.geography_match >= GeographyMatch.PREFIX and field_ratio >= 0.5:
        level = ConfidenceLevel.medium
    elif inp.geography_match >= GeographyMatch.DISTRICT and field_ratio >= 0.25:
        level = ConfidenceLevel.low
    elif score >= 0.5:
        level = ConfidenceLevel.medium
    elif score >= 0.25:
        level = ConfidenceLevel.low
    else:
        level = ConfidenceLevel.insufficient_evidence

    return level, round(score, 3), reasons


def confidence_from_signal_fields(
    geography_match: GeographyMatch,
    dso: str | None = None,
    service_type: str | None = None,
    location_type: str | None = None,
    capacity_kw: float | None = None,
    guide_price: float | None = None,
    payment_type: str | None = None,
    duration_minutes: float | None = None,
    window_start: str | None = None,
    lead_time: str | None = None,
    eligible_asset_types: list | None = None,
    source_updated_at: str | None = None,
) -> tuple[ConfidenceLevel, float, list[str]]:
    """Convenience wrapper: compute confidence from raw signal fields."""
    fields_present = sum([
        bool(dso),
        bool(service_type),
        location_type not in (None, "unknown"),
        capacity_kw is not None,
        guide_price is not None or payment_type is not None,
        duration_minutes is not None or window_start is not None or lead_time is not None,
        bool(eligible_asset_types),
        source_updated_at is not None,
    ])

    inp = ConfidenceInput(
        geography_match=geography_match,
        fields_present=fields_present,
        fields_total=len(KEY_FIELDS),
        has_capacity=capacity_kw is not None,
        has_price=guide_price is not None or payment_type is not None,
        has_timing=duration_minutes is not None or window_start is not None or lead_time is not None,
        has_eligible_assets=bool(eligible_asset_types),
    )

    return score_confidence(inp)

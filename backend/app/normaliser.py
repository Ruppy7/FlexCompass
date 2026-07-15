"""Normalisers: raw portal records → FlexZone / FlexSignal models.

Each normaliser handles the field mapping from a specific portal's raw format
to the zone-authoritative model. Preserves raw_record and source_dataset_id.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .confidence import (
    GeographyMatch,
    confidence_from_signal_fields,
)
from .models import (
    Direction,
    FlexSignal,
    FlexZone,
    HistoricCurrentFuture,
    LocationType,
    RequirementType,
    ServiceType,
)


def _stable_id(prefix: str, raw: dict[str, Any]) -> str:
    """Generate a deterministic ID from raw record content."""
    content = json.dumps(raw, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha256(content.encode()).hexdigest()[:12]
    return f"{prefix}_{h}"


def _safe_str(val: Any, default: str = "") -> str:
    if val is None:
        return default
    return str(val).strip()


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _map_service_type(raw: str | None) -> ServiceType:
    """Map raw service type string to enum."""
    if not raw:
        return ServiceType.demand_turn_down  # sensible default
    raw_lower = raw.lower().strip()
    mapping = {
        "demand_turn_down": ServiceType.demand_turn_down,
        "dtd": ServiceType.demand_turn_down,
        "demand turn down": ServiceType.demand_turn_down,
        "demand_turn_up": ServiceType.demand_turn_up,
        "dtu": ServiceType.demand_turn_up,
        "demand turn up": ServiceType.demand_turn_up,
        "generation_turn_up": ServiceType.generation_turn_up,
        "gtu": ServiceType.generation_turn_up,
        "generation turn up": ServiceType.generation_turn_up,
        "generation_turn_down": ServiceType.generation_turn_down,
        "gtd": ServiceType.generation_turn_down,
        "generation turn down": ServiceType.generation_turn_down,
    }
    return mapping.get(raw_lower, ServiceType.demand_turn_down)


def _map_direction(raw: str | None) -> Direction | None:
    """Map raw direction string to enum."""
    if not raw:
        return None
    raw_lower = raw.lower().strip()
    mapping = {
        "demand_turn_down": Direction.demand_turn_down,
        "demand_turn_up": Direction.demand_turn_up,
        "generation_turn_up": Direction.generation_turn_up,
        "generation_turn_down": Direction.generation_turn_down,
    }
    return mapping.get(raw_lower)


def _map_requirement_type(raw: str | None) -> RequirementType:
    if not raw:
        return RequirementType.unknown
    raw_lower = raw.lower().strip()
    mapping = {
        "long_term": RequirementType.long_term,
        "long term": RequirementType.long_term,
        "long-term": RequirementType.long_term,
        "short_term": RequirementType.short_term,
        "short term": RequirementType.short_term,
        "day_ahead": RequirementType.day_ahead,
        "day ahead": RequirementType.day_ahead,
        "intraday": RequirementType.intraday,
    }
    return mapping.get(raw_lower, RequirementType.unknown)


# ---------------------------------------------------------------------------
# NGED Normaliser
# ---------------------------------------------------------------------------

def normalise_nged_zone(raw: dict[str, Any]) -> FlexZone:
    """Normalise a raw NGED zone record into a FlexZone.

    Expected raw fields (unverified — from brief):
      zone, area_name, zone_type, postcodes, geometry
    """
    zone_id = _safe_str(raw.get("zone") or raw.get("zone_id"), "nged_unknown")
    if not zone_id.startswith("nged_"):
        zone_id = f"nged_{zone_id}"

    return FlexZone(
        zone_id=zone_id,
        dso="NGED",
        platform=None,
        area_name=_safe_str(raw.get("area_name") or raw.get("zone"), zone_id),
        zone_type=_safe_str(raw.get("zone_type"), "constraint_zone"),
        postcode_prefixes=raw.get("postcode_prefixes", []),
        postcodes=raw.get("postcodes", []),
        geometry=raw.get("geometry"),
        source_dataset_id=_safe_str(raw.get("source_dataset_id")),
        raw_record=raw,
    )


def normalise_nged_signal(
    raw: dict[str, Any],
    zone_id: str | None = None,
    source_dataset_id: str | None = None,
) -> FlexSignal:
    """Normalise a raw NGED trade record into a FlexSignal.

    Expected raw fields (unverified — from brief):
      trade_id, zone, service_type, direction, round, status,
      mw_requirement, guide_price, window_start, window_end
    """
    trade_id = _safe_str(raw.get("trade_id"), _stable_id("sig_nged", raw))
    service_type = _map_service_type(raw.get("service_type"))
    direction = _map_direction(raw.get("direction"))
    capacity_mw = _safe_float(raw.get("mw_requirement"))
    capacity_kw = capacity_mw * 1000 if capacity_mw is not None else None
    guide_price = _safe_float(raw.get("guide_price"))
    round_str = _safe_str(raw.get("round"))
    status = _safe_str(raw.get("status"), "unknown")

    # Map status to historic/current/future
    status_lower = status.lower()
    if "historic" in status_lower or "completed" in status_lower:
        hcfs = HistoricCurrentFuture.historic
    elif "current" in status_lower or "active" in status_lower:
        hcfs = HistoricCurrentFuture.current
    elif "future" in status_lower or "upcoming" in status_lower:
        hcfs = HistoricCurrentFuture.future
    else:
        hcfs = HistoricCurrentFuture.unknown

    # Determine requirement type from round/tender info
    req_type = RequirementType.long_term  # NGED trades are typically long-term

    zone = _safe_str(raw.get("zone"))
    resolved_zone_id = zone_id or (f"nged_{zone}" if zone else None)

    # Compute confidence
    geo_match = GeographyMatch.PREFIX  # NGED zones are postcode-prefix based
    conf_level, conf_score, conf_reasons = confidence_from_signal_fields(
        geography_match=geo_match,
        dso="NGED",
        service_type=service_type.value,
        location_type="zone",
        capacity_kw=capacity_kw,
        guide_price=guide_price,
        duration_minutes=_safe_float(raw.get("duration_minutes")),
        window_start=raw.get("window_start"),
        lead_time=raw.get("lead_time"),
        eligible_asset_types=raw.get("eligible_asset_types", ["ev_charger", "battery"]),
        source_updated_at=raw.get("source_updated_at"),
    )

    return FlexSignal(
        signal_id=f"sig_{trade_id}",
        zone_id=resolved_zone_id,
        dso="NGED",
        platform=None,
        market_name=f"NGED Flexibility — {zone or 'Unknown'}",
        area_name=_safe_str(raw.get("area_name") or zone, "Unknown"),
        location_type=LocationType.zone,
        location_reference=resolved_zone_id or "",
        service_type=service_type,
        direction=direction,
        requirement_type=req_type,
        tender_round=round_str or None,
        historic_current_future_status=hcfs,
        procurement_type="long_term",
        window_start=raw.get("window_start"),
        window_end=raw.get("window_end"),
        duration_minutes=_safe_float(raw.get("duration_minutes")),
        lead_time=raw.get("lead_time"),
        capacity_kw=capacity_kw,
        guide_price=guide_price,
        price_unit=raw.get("price_unit", "£/kW/year"),
        utilisation_estimate=raw.get("utilisation_estimate"),
        payment_type=raw.get("payment_type"),
        eligible_asset_types=raw.get("eligible_asset_types", []),
        source_id=None,
        source_updated_at=raw.get("source_updated_at"),
        source_dataset_id=source_dataset_id,
        raw_record=raw,
        confidence_level=conf_level,
        missing_fields=[],
        data_quality_notes=conf_reasons,
    )


# ---------------------------------------------------------------------------
# SPEN Normaliser (OpenDataSoft format)
# ---------------------------------------------------------------------------

def normalise_spen_signal(
    raw: dict[str, Any],
    zone_id: str | None = None,
    source_dataset_id: str | None = None,
) -> FlexSignal:
    """Normalise a raw SPEN record into a FlexSignal.

    SPEN's flexibility_competitions dataset (37k records, access-restricted)
    likely has fields like: zone, service_type, capacity, price, direction.
    Field names are unverified — this normaliser handles best-effort mapping.
    """
    record_id = _safe_str(
        raw.get("record_id") or raw.get("id"),
        _stable_id("sig_spen", raw),
    )

    service_type = _map_service_type(
        raw.get("service_type") or raw.get("service")
    )
    direction = _map_direction(raw.get("direction"))
    capacity_kw = _safe_float(raw.get("capacity_kw") or raw.get("mw_requirement"))
    if capacity_kw is None:
        capacity_mw = _safe_float(raw.get("capacity_mw"))
        if capacity_mw is not None:
            capacity_kw = capacity_mw * 1000
    guide_price = _safe_float(raw.get("guide_price") or raw.get("price"))

    zone = _safe_str(raw.get("zone") or raw.get("constraint_zone"))
    resolved_zone_id = zone_id or (f"spen_{zone}" if zone else None)

    conf_level, conf_score, conf_reasons = confidence_from_signal_fields(
        geography_match=GeographyMatch.PREFIX,
        dso="SPEN",
        service_type=service_type.value,
        location_type="zone",
        capacity_kw=capacity_kw,
        guide_price=guide_price,
    )

    return FlexSignal(
        signal_id=f"sig_spen_{record_id}",
        zone_id=resolved_zone_id,
        dso="SPEN",
        platform="Electron",
        market_name=f"SPEN Flexibility — {zone or 'Unknown'}",
        area_name=_safe_str(raw.get("area_name") or zone, "Unknown"),
        location_type=LocationType.zone,
        location_reference=resolved_zone_id or "",
        service_type=service_type,
        direction=direction,
        requirement_type=_map_requirement_type(raw.get("requirement_type")),
        tender_round=raw.get("tender_round"),
        historic_current_future_status=HistoricCurrentFuture.unknown,
        procurement_type=_safe_str(raw.get("procurement_type"), "unknown"),
        window_start=raw.get("window_start"),
        window_end=raw.get("window_end"),
        duration_minutes=_safe_float(raw.get("duration_minutes")),
        lead_time=raw.get("lead_time"),
        capacity_kw=capacity_kw,
        guide_price=guide_price,
        price_unit=raw.get("price_unit"),
        utilisation_estimate=raw.get("utilisation_estimate"),
        payment_type=raw.get("payment_type"),
        eligible_asset_types=raw.get("eligible_asset_types", []),
        source_updated_at=raw.get("source_updated_at"),
        source_dataset_id=source_dataset_id,
        raw_record=raw,
        confidence_level=conf_level,
        missing_fields=[],
        data_quality_notes=conf_reasons,
    )


# ---------------------------------------------------------------------------
# Generic batch normaliser
# ---------------------------------------------------------------------------

def normalise_records(
    records: list[dict[str, Any]],
    dso: str,
    zone_id_fn: Any = None,
    source_dataset_id: str | None = None,
) -> list[FlexSignal]:
    """Batch normalise raw records for any DSO.

    Args:
        records: Raw records from portal
        dso: DSO name (NGED, SPEN, ENWL, SSEN)
        zone_id_fn: Optional function to derive zone_id from a raw record
        source_dataset_id: Source dataset ID for provenance
    """
    normalisers = {
        "NGED": normalise_nged_signal,
        "SPEN": normalise_spen_signal,
    }

    normaliser = normalisers.get(dso.upper())
    if normaliser is None:
        raise ValueError(
            f"No normaliser for DSO '{dso}'. Available: {list(normalisers.keys())}"
        )

    signals = []
    for raw in records:
        zid = zone_id_fn(raw) if zone_id_fn else None
        signals.append(normaliser(raw, zone_id=zid, source_dataset_id=source_dataset_id))
    return signals

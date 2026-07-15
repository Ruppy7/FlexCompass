"""Pydantic models for FlexCompass v0.1 — zone-authoritative data model.

Entities from the brief:
  PortalDataset  — metadata about each portal dataset we consume
  FlexZone       — zone_id, dso, platform, area_name, geometry/boundary, provenance
  FlexSignal     — per-zone flexibility signal (enhanced from v0)
  AssetGroup     — real or synthetic asset group (enhanced from v0)
  AssetSignalMatch — match between asset group and signal (new)
  DataSource     — v0 provenance tracker (kept for backward compat)
  MarketRule     — v0 market rules (kept for backward compat)
  Portfolio      — v0 portfolio wrapper (kept for backward compat)
  FitAssessment  — v0 7-check assessment (kept for backward compat)
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums — existing (v0)
# ---------------------------------------------------------------------------

class SourceType(str, Enum):
    api = "api"
    csv = "csv"
    pdf = "pdf"
    webpage = "webpage"
    curated_seed = "curated_seed"


class LiveOrCurated(str, Enum):
    live = "live"
    curated = "curated"


class ConfidenceLevel(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"
    insufficient_evidence = "insufficient_evidence"
    unknown = "unknown"


class AssetType(str, Enum):
    ev_charger = "ev_charger"
    battery = "battery"
    generator = "generator"
    heat_pump = "heat_pump"
    solar_pv = "solar_pv"
    ci_load = "ci_load"


class ServiceType(str, Enum):
    demand_turn_down = "demand_turn_down"
    demand_turn_up = "demand_turn_up"
    generation_turn_up = "generation_turn_up"
    generation_turn_down = "generation_turn_down"


class LocationType(str, Enum):
    dso_region = "dso_region"
    zone = "zone"
    postcode_group = "postcode_group"
    gsp = "gsp"
    substation = "substation"
    polygon = "polygon"
    unknown = "unknown"


class PriorityBand(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"
    insufficient_evidence = "insufficient_evidence"


class RatingLevel(str, Enum):
    strong = "strong"
    partial = "partial"
    weak = "weak"
    unknown = "unknown"


class CompatibilityLevel(str, Enum):
    compatible = "compatible"
    partial = "partial"
    unclear = "unclear"
    incompatible = "incompatible"


class TemporalLevel(str, Enum):
    plausible = "plausible"
    uncertain = "uncertain"
    unlikely = "unlikely"
    unknown = "unknown"


class DataCompleteness(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class OperationalComplexity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    unknown = "unknown"


class MarketRuleClarity(str, Enum):
    clear = "clear"
    partial = "partial"
    weak = "weak"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# Enums — new for v0.1
# ---------------------------------------------------------------------------

class Direction(str, Enum):
    """Flexibility direction: turn up or turn down for demand or generation."""
    demand_turn_down = "demand_turn_down"
    demand_turn_up = "demand_turn_up"
    generation_turn_up = "generation_turn_up"
    generation_turn_down = "generation_turn_down"


class RequirementType(str, Enum):
    long_term = "long_term"
    short_term = "short_term"
    day_ahead = "day_ahead"
    intraday = "intraday"
    unknown = "unknown"


class HistoricCurrentFuture(str, Enum):
    historic = "historic"
    current = "current"
    future = "future"
    unknown = "unknown"


class AssetSource(str, Enum):
    real = "real"
    synthetic = "synthetic"


class GenerateAssetGroupRequest(BaseModel):
    """Request body for /api/asset-groups/generate."""
    asset_type: str
    count: int
    region: str


# ---------------------------------------------------------------------------
# v0.1 entities
# ---------------------------------------------------------------------------

class PortalDataset(BaseModel):
    """Metadata about a single dataset from a DSO open-data portal."""
    id: str
    name: str
    portal_url: str
    api_url: Optional[str] = None
    record_count: Optional[int] = None
    last_modified: Optional[str] = None
    licence: Optional[str] = None
    fields: list[str] = Field(default_factory=list)
    useful_for: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class FlexZone(BaseModel):
    """A DSO flexibility zone — the authoritative geographic unit."""
    zone_id: str
    dso: str
    platform: Optional[str] = None  # e.g. "Electron"
    area_name: str
    zone_type: str = "unknown"  # e.g. "constraint_zone", "substation_area"
    postcode_prefixes: list[str] = Field(default_factory=list)
    postcodes: list[str] = Field(default_factory=list)
    geometry: Optional[dict[str, Any]] = None  # GeoJSON geometry or ref
    source_dataset_id: Optional[str] = None
    raw_record: Optional[dict[str, Any]] = None


class FlexSignal(BaseModel):
    """Per-zone flexibility signal — enhanced for v0.1 zone-authoritative model.

    Backward compatible with v0: all new fields are Optional with sensible defaults.
    """
    signal_id: str
    zone_id: Optional[str] = None
    dso: str
    platform: Optional[str] = None
    market_name: str
    area_name: str
    location_type: LocationType = LocationType.unknown
    location_reference: str
    service_type: ServiceType
    direction: Optional[Direction] = None
    requirement_type: Optional[RequirementType] = None
    tender_round: Optional[str] = None
    historic_current_future_status: HistoricCurrentFuture = HistoricCurrentFuture.unknown
    procurement_type: str
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    duration_minutes: Optional[float] = None
    lead_time: Optional[str] = None
    capacity_kw: Optional[float] = None
    guide_price: Optional[float] = None
    price_unit: Optional[str] = None
    utilisation_estimate: Optional[str] = None
    payment_type: Optional[str] = None
    eligible_asset_types: list[AssetType] = Field(default_factory=list)
    source_id: Optional[str] = None  # v0 compat — maps to source_dataset_id
    source_updated_at: Optional[str] = None
    source_dataset_id: Optional[str] = None
    raw_record: Optional[dict[str, Any]] = None
    confidence_level: ConfidenceLevel = ConfidenceLevel.unknown
    missing_fields: list[str] = Field(default_factory=list)
    data_quality_notes: list[str] = Field(default_factory=list)


class AssetGroup(BaseModel):
    """Real or synthetic asset group — enhanced for v0.1.

    Backward compatible: regional_distribution / postcode_distribution kept
    for v0 portfolio matching.
    """
    asset_group_id: Optional[str] = None
    source: AssetSource = AssetSource.synthetic
    asset_type: AssetType
    asset_count: int
    postcode: Optional[str] = None
    postcode_prefix: Optional[str] = None
    rated_power_kw: float
    controllable_power_kw: float
    availability_percent: float
    response_reliability_percent: float
    supported_service_types: list[ServiceType] = Field(default_factory=list)
    regional_distribution: dict[str, float] = Field(default_factory=dict)
    postcode_distribution: dict[str, float] = Field(default_factory=dict)
    baseline_assumption: str = ""
    metering_assumption: str = ""
    operational_notes: list[str] = Field(default_factory=list)


class AssetSignalMatch(BaseModel):
    """Match between an AssetGroup and a FlexSignal with capacity estimates."""
    match_id: str
    asset_group_id: str
    signal_id: str
    mapped_zone_id: Optional[str] = None
    estimated_available_kw: float
    capacity_method: str = "v0.1_heuristic"
    geography_match: Optional[str] = None  # e.g. "full_postcode", "prefix", "zone"
    service_match: Optional[str] = None
    capacity_plausibility: Optional[str] = None
    data_completeness: Optional[str] = None
    investigation_priority: Optional[str] = None
    evidence: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# v0 entities (backward compat — still used by routes, matching, report)
# ---------------------------------------------------------------------------

class DataSource(BaseModel):
    source_id: str
    owner: str
    source_name: str
    source_type: SourceType
    access_method: str
    original_reference: str
    live_or_curated: LiveOrCurated
    date_accessed: str
    represented_period: str
    licence_notes: str
    update_frequency: str
    data_quality_notes: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class MarketRule(BaseModel):
    rule_id: str
    market_name: str
    buyer: str
    procurement_method: str
    payment_type: str
    eligible_provider_types: list[str] = Field(default_factory=list)
    eligible_asset_types: list[AssetType] = Field(default_factory=list)
    minimum_capacity_kw: float = 0
    metering_requirements: str
    baseline_requirements: str
    stacking_notes: str
    participation_notes: str
    source_id: str
    confidence_level: ConfidenceLevel = ConfidenceLevel.unknown


class Portfolio(BaseModel):
    portfolio_id: str
    portfolio_name: str
    assets: list[AssetGroup]


class FitAssessment(BaseModel):
    assessment_id: str
    portfolio_id: str
    signal_id: str
    estimated_available_kw: float
    investigation_priority_band: PriorityBand
    investigation_priority_score_optional: Optional[float] = None
    location_evidence: RatingLevel
    asset_type_compatibility: CompatibilityLevel
    capacity_plausibility: RatingLevel
    temporal_feasibility: TemporalLevel
    market_rule_clarity: MarketRuleClarity
    data_completeness: DataCompleteness
    operational_complexity: OperationalComplexity
    evidence_summary: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    disclaimer: str


# ---------------------------------------------------------------------------
# API request / response wrappers (v0, backward compat)
# ---------------------------------------------------------------------------

class AnalyseRequest(BaseModel):
    portfolio: Portfolio


class AnalyseResponse(BaseModel):
    portfolio: Portfolio
    assessments: list[FitAssessment]
    signals_considered: int
    sources_represented: list[str]
    dsos_represented: list[str]


class ReportRequest(BaseModel):
    portfolio: Portfolio


class ReportResponse(BaseModel):
    markdown: str
    portfolio: Portfolio
    assessments: list[FitAssessment]

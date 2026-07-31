/* TypeScript types matching backend Pydantic models — v0.1 */

export type ServiceType =
  | "demand_turn_down"
  | "demand_turn_up"
  | "generation_turn_up"
  | "generation_turn_down";

export type AssetType =
  | "ev_charger"
  | "battery"
  | "generator"
  | "heat_pump"
  | "solar_pv"
  | "ci_load";

export type PriorityBand = "high" | "medium" | "low" | "insufficient_evidence";
export type RatingLevel = "strong" | "partial" | "weak" | "unknown";
export type CompatibilityLevel = "compatible" | "partial" | "unclear" | "incompatible";
export type TemporalLevel = "plausible" | "uncertain" | "unlikely" | "unknown";
export type DataCompleteness = "high" | "medium" | "low";
export type OperationalComplexity = "low" | "medium" | "high" | "unknown";
export type MarketRuleClarity = "clear" | "partial" | "weak" | "unknown";
export type ConfidenceLevel = "high" | "medium" | "low" | "insufficient_evidence" | "unknown";

export interface AssetGroup {
  asset_group_id?: string;
  source: "real" | "synthetic";
  asset_type: AssetType;
  asset_count: number;
  postcode?: string;
  postcode_prefix?: string;
  rated_power_kw: number;
  controllable_power_kw: number;
  availability_percent: number;
  response_reliability_percent: number;
  supported_service_types: ServiceType[];
  regional_distribution: Record<string, number>;
  postcode_distribution: Record<string, number>;
  baseline_assumption: string;
  metering_assumption: string;
  operational_notes: string[];
}

export interface Portfolio {
  portfolio_id: string;
  portfolio_name: string;
  assets: AssetGroup[];
}

export interface FlexSignal {
  signal_id: string;
  zone_id?: string;
  source_id?: string;
  dso: string;
  platform?: string;
  market_name: string;
  area_name: string;
  location_type: string;
  location_reference: string;
  service_type: ServiceType;
  direction?: string;
  requirement_type?: string;
  tender_round?: string;
  historic_current_future_status?: string;
  procurement_type: string;
  window_start: string | null;
  window_end: string | null;
  duration_minutes: number | null;
  lead_time: string | null;
  capacity_kw: number | null;
  guide_price: number | null;
  price_unit: string | null;
  utilisation_estimate: string | null;
  payment_type: string | null;
  eligible_asset_types: AssetType[];
  source_updated_at: string | null;
  confidence_level: ConfidenceLevel;
  missing_fields?: string[];
  data_quality_notes: string[];
}

export interface FlexZone {
  zone_id: string;
  dso: string;
  platform?: string;
  area_name: string;
  zone_type: string;
  postcode_prefixes: string[];
  postcodes: string[];
  source_dataset_id?: string;
}

export interface PortalDataset {
  id: string;
  name: string;
  portal_url: string;
  api_url?: string;
  record_count?: number;
  licence?: string;
  fields: string[];
  useful_for: string[];
  limitations: string[];
}

export interface FitAssessment {
  assessment_id: string;
  portfolio_id: string;
  signal_id: string;
  estimated_available_kw: number;
  investigation_priority_band: PriorityBand;
  investigation_priority_score_optional: number | null;
  location_evidence: RatingLevel;
  asset_type_compatibility: CompatibilityLevel;
  capacity_plausibility: RatingLevel;
  temporal_feasibility: TemporalLevel;
  market_rule_clarity: MarketRuleClarity;
  data_completeness: DataCompleteness;
  operational_complexity: OperationalComplexity;
  evidence_summary: string[];
  missing_information: string[];
  risk_flags: string[];
  next_steps: string[];
  disclaimer: string;
}

export interface AnalyseResponse {
  workflow_kind: "synthetic_demo";
  portal_data_used: false;
  portfolio: Portfolio;
  assessments: FitAssessment[];
  signals_considered: number;
  sources_represented: string[];
  dsos_represented: string[];
}

export interface ReportResponse {
  workflow_kind: "synthetic_demo";
  portal_data_used: false;
  markdown: string;
  portfolio: Portfolio;
  assessments: FitAssessment[];
}

export interface DemoPortfolioListResponse {
  workflow_kind: "synthetic_demo";
  portal_data_used: false;
  items: Portfolio[];
}

export interface IngestStatus {
  ingested_tables: Record<string, number>;
  total_records: number;
}

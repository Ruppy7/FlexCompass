/* TypeScript types matching backend Pydantic models — v0.1 */

export type ServiceType =
  | "demand_turn_down"
  | "demand_turn_up"
  | "generation_turn_up"
  | "generation_turn_down";
export type Direction = ServiceType;
export type LocationType =
  | "dso_region"
  | "zone"
  | "postcode_group"
  | "gsp"
  | "substation"
  | "polygon"
  | "unknown";
export type RequirementType =
  | "long_term"
  | "short_term"
  | "day_ahead"
  | "intraday"
  | "unknown";
export type HistoricCurrentFutureStatus =
  | "historic"
  | "current"
  | "future"
  | "unknown";

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
  zone_id: string | null;
  dso: string;
  platform: string | null;
  market_name: string | null;
  area_name: string | null;
  location_type: LocationType | null;
  location_reference: string | null;
  service_type: ServiceType | null;
  direction: Direction | null;
  requirement_type: RequirementType | null;
  tender_round: string | null;
  historic_current_future_status: HistoricCurrentFutureStatus;
  procurement_type: string | null;
  window_start: string | null;
  window_end: string | null;
  duration_minutes: number | null;
  lead_time: string | null;
  capacity_kw: number | null;
  guide_price: number | null;
  price_unit: string | null;
  utilisation_estimate: string | null;
  payment_type: string | null;
  eligible_asset_types: AssetType[] | null;
  source_id: string | null;
  source_updated_at: string | null;
  source_dataset_id: string | null;
  raw_record: Record<string, unknown> | null;
  confidence_level: ConfidenceLevel;
  missing_fields: string[];
  data_quality_notes: string[];
}

export interface FlexZone {
  zone_id: string;
  dso: string;
  platform: string | null;
  area_name: string | null;
  zone_type: string | null;
  postcode_prefixes: string[];
  postcodes: string[];
  geometry: Record<string, unknown> | null;
  source_dataset_id: string | null;
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

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export type CatalogueTab = "coverage" | "datasets";

export type CataloguePortalId =
  | "nged"
  | "spen"
  | "enwl"
  | "ssen"
  | "ukpn"
  | "npg"
  | "neso";
export type CataloguePlatform = "ckan" | "opendatasoft";
export type CatalogueReviewStatus = "current" | "overdue" | "never_attempted";
export type CatalogueValidationState = "valid" | "invalid" | "unavailable";
export type CatalogueObservationStatus = "complete" | "partial" | "failed";
export type CatalogueLifecycleStatus =
  | "active"
  | "historical_archive"
  | "superseded"
  | "retired"
  | "unknown";
export type CataloguePublicationPattern =
  | "continuous"
  | "periodic"
  | "event_driven"
  | "static_reference"
  | "closed_period"
  | "unknown";
export type CatalogueAccessStatus =
  | "public"
  | "registered"
  | "restricted"
  | "unreachable"
  | "unknown";
export type CatalogueMaintenanceState =
  | "on_schedule"
  | "possibly_overdue"
  | "stale"
  | "expected_dormant"
  | "unknown";
export type CatalogueEvidenceConfidence = "high" | "medium" | "low" | "unknown";

export interface CatalogueRequestOptions {
  signal?: AbortSignal;
}

export interface CatalogueDatasetFilters {
  portalId?: CataloguePortalId;
  query?: string;
  lifecycle?: CatalogueLifecycleStatus;
  publication?: CataloguePublicationPattern;
  access?: CatalogueAccessStatus;
  maintenance?: CatalogueMaintenanceState;
  limit?: number;
  offset?: number;
}

export interface CatalogueObservationFilters {
  portalId?: CataloguePortalId;
  status?: CatalogueObservationStatus;
  limit?: number;
  offset?: number;
}

export interface CataloguePortalSummary {
  portal_id: CataloguePortalId;
  operator_name: string;
  platform: CataloguePlatform;
  portal_url: string | null;
  current_attempt_status: string | null;
  current_attempt_at: string | null;
  current_attempt_warning_count: number;
  operational_review_window_hours: number;
  review_due_at: string | null;
  review_status: CatalogueReviewStatus;
  last_complete_observation_id: string | null;
  last_complete_observed_at: string | null;
  latest_complete_snapshot_valid: boolean | null;
  latest_complete_validation_state: CatalogueValidationState;
  last_valid_observation_id: string | null;
  last_valid_observed_at: string | null;
  last_valid_dataset_count: number;
  last_valid_resource_count: number;
  degraded: boolean;
  snapshot_available: boolean;
}

export interface CatalogueDatasetSummary {
  dataset_ref: string;
  portal_id: CataloguePortalId;
  source_dataset_id: string;
  title: string | null;
  description: string | null;
  publisher: string | null;
  licence: string | null;
  licence_identifier: string | null;
  licence_title: string | null;
  licence_url: string | null;
  attribution: string | null;
  themes: string[];
  catalogue_page_url: string | null;
  metadata_api_url: string | null;
  declared_update_frequency: string | null;
  declared_update_frequency_text: string | null;
  portal_url: string | null;
  api_url: string | null;
  source_created_at: string | null;
  source_updated_at: string | null;
  observed_at: string;
  lifecycle_status: CatalogueLifecycleStatus;
  publication_pattern: CataloguePublicationPattern;
  access_status: CatalogueAccessStatus;
  tags: string[];
}

export type CatalogueDatasetDetail = CatalogueDatasetSummary;

export interface CatalogueResource {
  id: string;
  portal_id: CataloguePortalId;
  source_dataset_id: string;
  name: string | null;
  description: string | null;
  url: string | null;
  format: string | null;
  media_type: string | null;
  size_bytes: number | null;
  source_created_at: string | null;
  source_updated_at: string | null;
  observed_at: string | null;
}

export interface CatalogueEvidence {
  id: string;
  portal_id: CataloguePortalId;
  source_dataset_id: string;
  classification: string;
  evidence: string;
  confidence: CatalogueEvidenceConfidence;
  source_url: string | null;
  observed_at: string | null;
}

export interface CatalogueAssessment {
  assessment_id: string;
  observation_id: string;
  assessment_type: string;
  assessment_value: string;
  confidence: string;
  assessed_at: string;
}

export interface CatalogueObservation {
  observation_id: string;
  portal_id: CataloguePortalId;
  observed_at: string | null;
  status: CatalogueObservationStatus;
  adapter_version: string | null;
  schema_version: number | null;
  content_hash: string | null;
  expected_count: number | null;
  dataset_count: number | null;
  resource_count: number | null;
  complete: boolean | null;
}

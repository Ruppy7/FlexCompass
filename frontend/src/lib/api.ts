/* API client for the explicitly synthetic FlexCompass demonstration. */

import type {
  AnalyseResponse,
  CatalogueAssessment,
  CatalogueDatasetDetail,
  CatalogueDatasetFilters,
  CatalogueDatasetSummary,
  CatalogueEvidence,
  CatalogueObservation,
  CatalogueObservationFilters,
  CataloguePortalId,
  CataloguePortalSummary,
  CatalogueRequestOptions,
  CatalogueResource,
  DemoPortfolioListResponse,
  Page,
  Portfolio,
  ReportResponse,
} from "./types";

const DEMO_BASE = "/api/demo";
const CATALOGUE_BASE = "/api/v1/catalogue";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function parseDemoResponse<T>(
  response: Response,
  failureMessage: string,
): Promise<T> {
  if (!response.ok) {
    throw new Error(failureMessage);
  }
  const payload: unknown = await response.json();
  if (
    !isRecord(payload)
    || payload.workflow_kind !== "synthetic_demo"
    || payload.portal_data_used !== false
  ) {
    throw new Error("Invalid synthetic demonstration response");
  }
  return payload as T;
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isBoolean(value: unknown): value is boolean {
  return typeof value === "boolean";
}

function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && Number.isInteger(value);
}

function isNullable<T>(
  value: unknown,
  validator: (candidate: unknown) => candidate is T,
): value is T | null {
  return value === null || validator(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString);
}

function isOneOf(value: unknown, allowed: readonly string[]): value is string {
  return isString(value) && allowed.includes(value);
}

const PORTAL_IDS = ["nged", "spen", "enwl", "ssen", "ukpn", "npg", "neso"];
const PLATFORMS = ["ckan", "opendatasoft"];
const REVIEW_STATUSES = ["current", "overdue", "never_attempted"];
const VALIDATION_STATES = ["valid", "invalid", "unavailable"];
const LIFECYCLE_STATUSES = [
  "active",
  "historical_archive",
  "superseded",
  "retired",
  "unknown",
];
const PUBLICATION_PATTERNS = [
  "continuous",
  "periodic",
  "event_driven",
  "static_reference",
  "closed_period",
  "unknown",
];
const ACCESS_STATUSES = [
  "public",
  "registered",
  "restricted",
  "unreachable",
  "unknown",
];
const EVIDENCE_CONFIDENCES = ["high", "medium", "low", "unknown"];
const OBSERVATION_STATUSES = ["complete", "partial", "failed"];

function isCataloguePortal(value: unknown): value is CataloguePortalSummary {
  return (
    isRecord(value)
    && isOneOf(value.portal_id, PORTAL_IDS)
    && isString(value.operator_name)
    && isOneOf(value.platform, PLATFORMS)
    && isNullable(value.portal_url, isString)
    && isNullable(value.current_attempt_status, isString)
    && isNullable(value.current_attempt_at, isString)
    && isInteger(value.current_attempt_warning_count)
    && isInteger(value.operational_review_window_hours)
    && isNullable(value.review_due_at, isString)
    && isOneOf(value.review_status, REVIEW_STATUSES)
    && isNullable(value.last_complete_observation_id, isString)
    && isNullable(value.last_complete_observed_at, isString)
    && isNullable(value.latest_complete_snapshot_valid, isBoolean)
    && isOneOf(value.latest_complete_validation_state, VALIDATION_STATES)
    && isNullable(value.last_valid_observation_id, isString)
    && isNullable(value.last_valid_observed_at, isString)
    && isInteger(value.last_valid_dataset_count)
    && isInteger(value.last_valid_resource_count)
    && isBoolean(value.degraded)
    && isBoolean(value.snapshot_available)
  );
}

function isCatalogueDataset(value: unknown): value is CatalogueDatasetSummary {
  return (
    isRecord(value)
    && isString(value.dataset_ref)
    && isOneOf(value.portal_id, PORTAL_IDS)
    && isString(value.source_dataset_id)
    && isNullable(value.title, isString)
    && isNullable(value.description, isString)
    && isNullable(value.publisher, isString)
    && isNullable(value.licence, isString)
    && isNullable(value.licence_identifier, isString)
    && isNullable(value.licence_title, isString)
    && isNullable(value.licence_url, isString)
    && isNullable(value.attribution, isString)
    && isStringArray(value.themes)
    && isNullable(value.catalogue_page_url, isString)
    && isNullable(value.metadata_api_url, isString)
    && isNullable(value.declared_update_frequency, isString)
    && isNullable(value.declared_update_frequency_text, isString)
    && isNullable(value.portal_url, isString)
    && isNullable(value.api_url, isString)
    && isNullable(value.source_created_at, isString)
    && isNullable(value.source_updated_at, isString)
    && isString(value.observed_at)
    && isOneOf(value.lifecycle_status, LIFECYCLE_STATUSES)
    && isOneOf(value.publication_pattern, PUBLICATION_PATTERNS)
    && isOneOf(value.access_status, ACCESS_STATUSES)
    && isStringArray(value.tags)
  );
}

function isCatalogueResource(value: unknown): value is CatalogueResource {
  return (
    isRecord(value)
    && isString(value.id)
    && isOneOf(value.portal_id, PORTAL_IDS)
    && isString(value.source_dataset_id)
    && isNullable(value.name, isString)
    && isNullable(value.description, isString)
    && isNullable(value.url, isString)
    && isNullable(value.format, isString)
    && isNullable(value.media_type, isString)
    && isNullable(value.size_bytes, isInteger)
    && isNullable(value.source_created_at, isString)
    && isNullable(value.source_updated_at, isString)
    && isNullable(value.observed_at, isString)
  );
}

function isCatalogueEvidence(value: unknown): value is CatalogueEvidence {
  return (
    isRecord(value)
    && isString(value.id)
    && isOneOf(value.portal_id, PORTAL_IDS)
    && isString(value.source_dataset_id)
    && isString(value.classification)
    && isString(value.evidence)
    && isOneOf(value.confidence, EVIDENCE_CONFIDENCES)
    && isNullable(value.source_url, isString)
    && isNullable(value.observed_at, isString)
  );
}

function isCatalogueAssessment(value: unknown): value is CatalogueAssessment {
  return (
    isRecord(value)
    && isString(value.assessment_id)
    && isString(value.observation_id)
    && isString(value.assessment_type)
    && isString(value.assessment_value)
    && isString(value.confidence)
    && isString(value.assessed_at)
  );
}

function isCatalogueObservation(value: unknown): value is CatalogueObservation {
  return (
    isRecord(value)
    && isString(value.observation_id)
    && isOneOf(value.portal_id, PORTAL_IDS)
    && isNullable(value.observed_at, isString)
    && isOneOf(value.status, OBSERVATION_STATUSES)
    && isNullable(value.adapter_version, isString)
    && isNullable(value.schema_version, isInteger)
    && isNullable(value.content_hash, isString)
    && isNullable(value.expected_count, isInteger)
    && isNullable(value.dataset_count, isInteger)
    && isNullable(value.resource_count, isInteger)
    && isNullable(value.complete, isBoolean)
  );
}

function isPageOf<T>(
  value: unknown,
  itemValidator: (item: unknown) => item is T,
): value is Page<T> {
  return (
    isRecord(value)
    && Array.isArray(value.items)
    && value.items.every(itemValidator)
    && isInteger(value.total)
    && value.total >= 0
    && isInteger(value.limit)
    && value.limit >= 1
    && value.limit <= 200
    && isInteger(value.offset)
    && value.offset >= 0
  );
}

export function isCatalogueAbortError(error: unknown): boolean {
  return isRecord(error) && error.name === "AbortError";
}

async function parseCatalogueResponse<T>(
  response: Response,
  failureMessage: string,
  invalidMessage: string,
  validator: (value: unknown) => boolean,
): Promise<T> {
  if (!response.ok) {
    throw new Error(failureMessage);
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error: unknown) {
    if (isCatalogueAbortError(error)) {
      throw error;
    }
    throw new Error(invalidMessage);
  }
  if (!validator(payload)) {
    throw new Error(invalidMessage);
  }
  return payload as T;
}

function catalogueRequestInit(options?: CatalogueRequestOptions): RequestInit {
  const request: RequestInit = { method: "GET" };
  if (options?.signal !== undefined) {
    request.signal = options.signal;
  }
  return request;
}

async function catalogueGet<T>(
  path: string,
  failureMessage: string,
  invalidMessage: string,
  validator: (value: unknown) => boolean,
  options?: CatalogueRequestOptions,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${CATALOGUE_BASE}${path}`, catalogueRequestInit(options));
  } catch (error: unknown) {
    if (isCatalogueAbortError(error)) {
      throw error;
    }
    throw new Error(failureMessage);
  }
  return parseCatalogueResponse<T>(
    response,
    failureMessage,
    invalidMessage,
    validator,
  );
}

function appendDefined(
  parameters: URLSearchParams,
  name: string,
  value: string | number | undefined,
): void {
  if (value !== undefined) {
    parameters.append(name, String(value));
  }
}

function withQuery(path: string, parameters: URLSearchParams): string {
  const query = parameters.toString();
  return query ? `${path}?${query}` : path;
}

export async function fetchCataloguePortals(
  options?: CatalogueRequestOptions,
): Promise<Page<CataloguePortalSummary>> {
  return catalogueGet(
    "/portals",
    "Failed to fetch catalogue portals",
    "Invalid catalogue portals response",
    (value): value is Page<CataloguePortalSummary> => (
      isPageOf(value, isCataloguePortal)
    ),
    options,
  );
}

export async function fetchCataloguePortal(
  portalId: CataloguePortalId,
  options?: CatalogueRequestOptions,
): Promise<CataloguePortalSummary> {
  return catalogueGet(
    `/portals/${encodeURIComponent(portalId)}`,
    "Failed to fetch catalogue portal",
    "Invalid catalogue portal response",
    isCataloguePortal,
    options,
  );
}

export async function fetchCatalogueDatasets(
  filters: CatalogueDatasetFilters,
  options?: CatalogueRequestOptions,
): Promise<Page<CatalogueDatasetSummary>> {
  const parameters = new URLSearchParams();
  appendDefined(parameters, "portal_id", filters.portalId);
  appendDefined(parameters, "q", filters.query);
  appendDefined(parameters, "lifecycle_status", filters.lifecycle);
  appendDefined(parameters, "publication_pattern", filters.publication);
  appendDefined(parameters, "access_status", filters.access);
  appendDefined(parameters, "maintenance_state", filters.maintenance);
  appendDefined(parameters, "limit", filters.limit);
  appendDefined(parameters, "offset", filters.offset);
  return catalogueGet(
    withQuery("/datasets", parameters),
    "Failed to fetch catalogue datasets",
    "Invalid catalogue datasets response",
    (value): value is Page<CatalogueDatasetSummary> => (
      isPageOf(value, isCatalogueDataset)
    ),
    options,
  );
}

export async function fetchCatalogueDataset(
  datasetRef: string,
  options?: CatalogueRequestOptions,
): Promise<CatalogueDatasetDetail> {
  return catalogueGet(
    `/datasets/${encodeURIComponent(datasetRef)}`,
    "Failed to fetch catalogue dataset",
    "Invalid catalogue dataset response",
    isCatalogueDataset,
    options,
  );
}

export async function fetchCatalogueDatasetResources(
  datasetRef: string,
  options?: CatalogueRequestOptions,
): Promise<Page<CatalogueResource>> {
  return catalogueGet(
    `/datasets/${encodeURIComponent(datasetRef)}/resources`,
    "Failed to fetch catalogue resources",
    "Invalid catalogue resources response",
    (value): value is Page<CatalogueResource> => (
      isPageOf(value, isCatalogueResource)
    ),
    options,
  );
}

export async function fetchCatalogueDatasetEvidence(
  datasetRef: string,
  options?: CatalogueRequestOptions,
): Promise<Page<CatalogueEvidence>> {
  return catalogueGet(
    `/datasets/${encodeURIComponent(datasetRef)}/evidence`,
    "Failed to fetch catalogue evidence",
    "Invalid catalogue evidence response",
    (value): value is Page<CatalogueEvidence> => (
      isPageOf(value, isCatalogueEvidence)
    ),
    options,
  );
}

export async function fetchCatalogueDatasetAssessments(
  datasetRef: string,
  options?: CatalogueRequestOptions,
): Promise<Page<CatalogueAssessment>> {
  return catalogueGet(
    `/datasets/${encodeURIComponent(datasetRef)}/assessments`,
    "Failed to fetch catalogue assessments",
    "Invalid catalogue assessments response",
    (value): value is Page<CatalogueAssessment> => (
      isPageOf(value, isCatalogueAssessment)
    ),
    options,
  );
}

export async function fetchCatalogueObservations(
  filters: CatalogueObservationFilters = {},
  options?: CatalogueRequestOptions,
): Promise<Page<CatalogueObservation>> {
  const parameters = new URLSearchParams();
  appendDefined(parameters, "portal_id", filters.portalId);
  appendDefined(parameters, "status", filters.status);
  appendDefined(parameters, "limit", filters.limit);
  appendDefined(parameters, "offset", filters.offset);
  return catalogueGet(
    withQuery("/observations", parameters),
    "Failed to fetch catalogue observations",
    "Invalid catalogue observations response",
    (value): value is Page<CatalogueObservation> => (
      isPageOf(value, isCatalogueObservation)
    ),
    options,
  );
}

export async function fetchDemoPortfolios(): Promise<Portfolio[]> {
  const response = await fetch(`${DEMO_BASE}/portfolios`, {
    method: "GET",
  });
  const payload = await parseDemoResponse<DemoPortfolioListResponse>(
    response,
    "Failed to fetch synthetic demonstration portfolios",
  );
  return payload.items;
}

export async function analyseDemoPortfolio(
  portfolio: Portfolio,
): Promise<AnalyseResponse> {
  const response = await fetch(`${DEMO_BASE}/analyse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ portfolio }),
  });
  return parseDemoResponse<AnalyseResponse>(
    response,
    "Synthetic demonstration analysis failed",
  );
}

export async function generateDemoReport(
  portfolio: Portfolio,
): Promise<ReportResponse> {
  const response = await fetch(`${DEMO_BASE}/report`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ portfolio }),
  });
  return parseDemoResponse<ReportResponse>(
    response,
    "Synthetic demonstration report generation failed",
  );
}

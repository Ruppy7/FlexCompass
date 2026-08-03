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

function isPage(value: unknown): value is Page<unknown> {
  return (
    isRecord(value)
    && Array.isArray(value.items)
    && typeof value.total === "number"
    && typeof value.limit === "number"
    && typeof value.offset === "number"
  );
}

function isAbortError(error: unknown): boolean {
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
    if (isAbortError(error)) {
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
  const response = await fetch(`${CATALOGUE_BASE}${path}`, catalogueRequestInit(options));
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
    isPage,
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
    isRecord,
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
    isPage,
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
    isRecord,
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
    isPage,
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
    isPage,
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
    isPage,
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
    isPage,
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

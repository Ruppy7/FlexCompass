import { vi } from "vitest";

import {
  analyseDemoPortfolio,
  fetchCatalogueDataset,
  fetchCatalogueDatasetAssessments,
  fetchCatalogueDatasetEvidence,
  fetchCatalogueDatasetResources,
  fetchCatalogueDatasets,
  fetchCatalogueObservations,
  fetchCataloguePortal,
  fetchCataloguePortals,
  fetchDemoPortfolios,
  generateDemoReport,
} from "./api";
import type { Portfolio } from "./types";

const DEMO_PORTFOLIO: Portfolio = {
  portfolio_id: "frontend-demo",
  portfolio_name: "Frontend synthetic demo",
  assets: [
    {
      source: "synthetic",
      asset_type: "battery",
      asset_count: 1,
      rated_power_kw: 10,
      controllable_power_kw: 5,
      availability_percent: 0.5,
      response_reliability_percent: 0.9,
      supported_service_types: [],
      regional_distribution: {},
      postcode_distribution: {},
      baseline_assumption: "",
      metering_assumption: "",
      operational_notes: [],
    },
  ],
};

function mockFetchJson(payload: object): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => payload,
    }),
  );
}

const VALID_ANALYSE_RESPONSE = {
  workflow_kind: "synthetic_demo",
  portal_data_used: false,
  portfolio: DEMO_PORTFOLIO,
  assessments: [],
  signals_considered: 0,
  sources_represented: [],
  dsos_represented: [],
};

const VALID_REPORT_RESPONSE = {
  workflow_kind: "synthetic_demo",
  portal_data_used: false,
  portfolio: DEMO_PORTFOLIO,
  assessments: [],
  markdown: "# Synthetic Flexibility Fit Demonstration",
};

const EMPTY_PAGE = { items: [], total: 0, limit: 50, offset: 0 };

function mockCatalogueFetch(payload: unknown = EMPTY_PAGE): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => payload,
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

it("uses the exact ordered backend dataset filter names and preserves the page", async () => {
  const expectedPage = { items: [], total: 71, limit: 25, offset: 50 };
  const fetchMock = mockCatalogueFetch(expectedPage);

  const page = await fetchCatalogueDatasets({
    portalId: "ssen",
    query: "outage",
    lifecycle: "active",
    publication: "periodic",
    access: "public",
    maintenance: "possibly_overdue",
    limit: 25,
    offset: 50,
  });

  expect(page).toEqual(expectedPage);
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/catalogue/datasets?portal_id=ssen&q=outage&lifecycle_status=active&publication_pattern=periodic&access_status=public&maintenance_state=possibly_overdue&limit=25&offset=50",
    { method: "GET" },
  );
});

it("omits undefined dataset filters without changing parameter order", async () => {
  const fetchMock = mockCatalogueFetch();

  await fetchCatalogueDatasets({ query: "network", offset: 0 });

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/catalogue/datasets?q=network&offset=0",
    { method: "GET" },
  );
  expect(String(fetchMock.mock.calls[0][0])).not.toContain("query=");
});

it("uses only versioned GET endpoints for every catalogue request", async () => {
  const fetchMock = mockCatalogueFetch();
  const datasetRef = "opaque-ref";

  await fetchCataloguePortals();
  await fetchCataloguePortal("ssen");
  await fetchCatalogueDatasets({});
  await fetchCatalogueDataset(datasetRef);
  await fetchCatalogueDatasetResources(datasetRef);
  await fetchCatalogueDatasetEvidence(datasetRef);
  await fetchCatalogueDatasetAssessments(datasetRef);
  await fetchCatalogueObservations();

  const calls = fetchMock.mock.calls;
  expect(calls).toHaveLength(8);
  for (const [url, init] of calls) {
    expect(String(url)).toMatch(/^\/api\/v1\/catalogue\//);
    expect(init).toEqual({ method: "GET" });
  }
  const urls = calls.map(([url]) => String(url));
  expect(urls.join(" ")).not.toMatch(/portal\/datasets|zones|signals|ingest/);
});

it("encodes opaque dataset references only at the path boundary", async () => {
  const fetchMock = mockCatalogueFetch(EMPTY_PAGE);
  const datasetRef = "folder/ref?query#fragment%value";
  const encodedRef = encodeURIComponent(datasetRef);

  await fetchCatalogueDataset(datasetRef);
  await fetchCatalogueDatasetResources(datasetRef);
  await fetchCatalogueDatasetEvidence(datasetRef);
  await fetchCatalogueDatasetAssessments(datasetRef);

  expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
    `/api/v1/catalogue/datasets/${encodedRef}`,
    `/api/v1/catalogue/datasets/${encodedRef}/resources`,
    `/api/v1/catalogue/datasets/${encodedRef}/evidence`,
    `/api/v1/catalogue/datasets/${encodedRef}/assessments`,
  ]);
});

it("uses deterministic observation filter names and preserves page metadata", async () => {
  const expectedPage = { items: [], total: 4, limit: 2, offset: 2 };
  const fetchMock = mockCatalogueFetch(expectedPage);

  const page = await fetchCatalogueObservations({
    portalId: "nged",
    status: "partial",
    limit: 2,
    offset: 2,
  });

  expect(page).toEqual(expectedPage);
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/catalogue/observations?portal_id=nged&status=partial&limit=2&offset=2",
    { method: "GET" },
  );
});

it("forwards AbortSignal only when the caller supplies it", async () => {
  const fetchMock = mockCatalogueFetch();
  const controller = new AbortController();

  await fetchCatalogueDatasets(
    { portalId: "ssen" },
    { signal: controller.signal },
  );

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/catalogue/datasets?portal_id=ssen",
    { method: "GET", signal: controller.signal },
  );
});

it.each([
  ["portals", () => fetchCataloguePortals(), "Failed to fetch catalogue portals"],
  [
    "portal",
    () => fetchCataloguePortal("ssen"),
    "Failed to fetch catalogue portal",
  ],
  [
    "datasets",
    () => fetchCatalogueDatasets({}),
    "Failed to fetch catalogue datasets",
  ],
  [
    "dataset",
    () => fetchCatalogueDataset("ref"),
    "Failed to fetch catalogue dataset",
  ],
  [
    "resources",
    () => fetchCatalogueDatasetResources("ref"),
    "Failed to fetch catalogue resources",
  ],
  [
    "evidence",
    () => fetchCatalogueDatasetEvidence("ref"),
    "Failed to fetch catalogue evidence",
  ],
  [
    "assessments",
    () => fetchCatalogueDatasetAssessments("ref"),
    "Failed to fetch catalogue assessments",
  ],
  [
    "observations",
    () => fetchCatalogueObservations(),
    "Failed to fetch catalogue observations",
  ],
])("maps non-2xx %s errors to fixed safe messages", async (_name, invoke, message) => {
  const rawSentinel = "private-upstream-body";
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ detail: rawSentinel }),
      text: async () => rawSentinel,
    }),
  );

  await expect(invoke()).rejects.toThrow(message);
  await expect(invoke()).rejects.not.toThrow(rawSentinel);
});

it.each([
  [
    "page",
    () => fetchCataloguePortals(),
    { items: [], total: 0, raw_private: "private-malformed-shape" },
  ],
  ["detail", () => fetchCatalogueDataset("ref"), ["private-malformed-shape"]],
])("rejects malformed catalogue %s shapes with stable safe errors", async (
  _name,
  invoke,
  payload,
) => {
  mockCatalogueFetch(payload);
  const rawSentinel = "private-malformed-shape";

  await expect(invoke()).rejects.toThrow(/invalid catalogue/i);
  await expect(invoke()).rejects.not.toThrow(rawSentinel);
});

it("maps malformed catalogue JSON to a stable message without raw parser text", async () => {
  const rawSentinel = "private-json-parser-detail";
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => {
        throw new SyntaxError(rawSentinel);
      },
    }),
  );

  await expect(fetchCataloguePortals()).rejects.toThrow(
    "Invalid catalogue portals response",
  );
  await expect(fetchCataloguePortals()).rejects.not.toThrow(rawSentinel);
});

it("does not swallow AbortError", async () => {
  const abortError = new DOMException("The operation was aborted", "AbortError");
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abortError));

  await expect(fetchCataloguePortals()).rejects.toBe(abortError);
});

it("uses only the labelled demo analysis contract", async () => {
  mockFetchJson({
    workflow_kind: "synthetic_demo",
    portal_data_used: false,
    portfolio: DEMO_PORTFOLIO,
    assessments: [],
    signals_considered: 0,
    sources_represented: [],
    dsos_represented: [],
  });

  await analyseDemoPortfolio(DEMO_PORTFOLIO);

  expect(fetch).toHaveBeenCalledWith(
    "/api/demo/analyse",
    expect.objectContaining({ method: "POST" }),
  );
  expect(
    JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body)),
  ).toEqual(
    expect.objectContaining({
      portfolio: expect.objectContaining({
        assets: [
          expect.objectContaining({ source: "synthetic" }),
        ],
      }),
    }),
  );
});

it.each([
  [
    "portfolios",
    () => fetchDemoPortfolios(),
    { items: [] },
  ],
  [
    "analyse",
    () => analyseDemoPortfolio(DEMO_PORTFOLIO),
    {
      ...VALID_ANALYSE_RESPONSE,
      workflow_kind: undefined,
    },
  ],
  [
    "report",
    () => generateDemoReport(DEMO_PORTFOLIO),
    {
      ...VALID_REPORT_RESPONSE,
      workflow_kind: "unlabelled",
    },
  ],
])("rejects a missing or wrong %s workflow label", async (_name, invoke, payload) => {
  mockFetchJson(payload);
  await expect(invoke()).rejects.toThrow(
    /invalid synthetic demonstration response/i,
  );
});

it.each([
  [
    "portfolios",
    () => fetchDemoPortfolios(),
    {
      workflow_kind: "synthetic_demo",
      portal_data_used: true,
      items: [],
    },
  ],
  [
    "analyse",
    () => analyseDemoPortfolio(DEMO_PORTFOLIO),
    {
      ...VALID_ANALYSE_RESPONSE,
      portal_data_used: true,
    },
  ],
  [
    "report",
    () => generateDemoReport(DEMO_PORTFOLIO),
    {
      ...VALID_REPORT_RESPONSE,
      portal_data_used: true,
    },
  ],
])("rejects %s data labelled as portal-derived", async (_name, invoke, payload) => {
  mockFetchJson(payload);
  await expect(invoke()).rejects.toThrow(
    /invalid synthetic demonstration response/i,
  );
});

it.each([
  [
    "portfolios",
    () => fetchDemoPortfolios(),
    "/api/demo/portfolios",
    "GET",
  ],
  [
    "analyse",
    () => analyseDemoPortfolio(DEMO_PORTFOLIO),
    "/api/demo/analyse",
    "POST",
  ],
  [
    "report",
    () => generateDemoReport(DEMO_PORTFOLIO),
    "/api/demo/report",
    "POST",
  ],
])(
  "uses the exact %s helper contract",
  async (_name, invoke, path, method) => {
    mockFetchJson(
      path.endsWith("/portfolios")
        ? {
            workflow_kind: "synthetic_demo",
            portal_data_used: false,
            items: [],
          }
        : {
            workflow_kind: "synthetic_demo",
            portal_data_used: false,
            portfolio: DEMO_PORTFOLIO,
            assessments: [],
            markdown: "",
            signals_considered: 0,
            sources_represented: [],
            dsos_represented: [],
          },
    );
    await invoke();
    expect(fetch).toHaveBeenLastCalledWith(
      path,
      expect.objectContaining({ method }),
    );
  },
);

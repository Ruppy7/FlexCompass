import { vi } from "vitest";

import {
  analyseDemoPortfolio,
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

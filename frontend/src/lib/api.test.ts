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

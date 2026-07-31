import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import SyntheticDemo from "./SyntheticDemo";

it("keeps the synthetic-data warning visible around the workflow", () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise(() => undefined)),
  );
  render(<SyntheticDemo />);
  expect(
    screen.getByText(/no live or current portal data is used/i),
  ).toBeVisible();
  expect(
    screen.getByRole("heading", { name: /portfolio input/i }),
  ).toBeVisible();
});

const DEMO_PORTFOLIO = {
  portfolio_id: "frontend-demo",
  portfolio_name: "Frontend synthetic demo",
  assets: [{
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
  }],
};

const EMPTY_ANALYSIS = {
  workflow_kind: "synthetic_demo",
  portal_data_used: false,
  portfolio: DEMO_PORTFOLIO,
  assessments: [],
  signals_considered: 0,
  sources_represented: [],
  dsos_represented: [],
};

const REPORT = {
  workflow_kind: "synthetic_demo",
  portal_data_used: false,
  portfolio: DEMO_PORTFOLIO,
  assessments: [],
  markdown: "# Synthetic Flexibility Fit Demonstration",
};

function response(payload: object, ok = true) {
  return Promise.resolve({
    ok,
    json: async () => payload,
  });
}

async function selectCustomAndRun(): Promise<void> {
  await userEvent.click(
    screen.getByRole("button", { name: /custom portfolio/i }),
  );
  await userEvent.click(
    screen.getByRole("button", { name: /run analysis/i }),
  );
}

it("states explicitly when no verified signals can produce fit assessments", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/portfolios")) {
        return response({
          workflow_kind: "synthetic_demo",
          portal_data_used: false,
          items: [],
        });
      }
      if (path.endsWith("/analyse")) {
        return response(EMPTY_ANALYSIS);
      }
      return response(REPORT);
    }),
  );
  render(<SyntheticDemo />);

  await selectCustomAndRun();

  expect(
    await screen.findByText(
      /no verified flexibility signals are available.*no fit assessments/i,
    ),
  ).toBeVisible();
});

it("removes stale output before showing a later run failure", async () => {
  const assessment = {
    assessment_id: "assessment-1",
    portfolio_id: "frontend-demo",
    signal_id: "synthetic-signal",
    estimated_available_kw: 5,
    investigation_priority_band: "insufficient_evidence",
    investigation_priority_score_optional: null,
    location_evidence: "unknown",
    asset_type_compatibility: "unclear",
    capacity_plausibility: "unknown",
    temporal_feasibility: "unknown",
    market_rule_clarity: "unknown",
    data_completeness: "low",
    operational_complexity: "unknown",
    evidence_summary: [],
    missing_information: [],
    risk_flags: [],
    next_steps: [],
    disclaimer: "Synthetic demonstration.",
  };
  let analysisCalls = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/portfolios")) {
        return response({
          workflow_kind: "synthetic_demo",
          portal_data_used: false,
          items: [],
        });
      }
      if (path.endsWith("/analyse")) {
        analysisCalls += 1;
        if (analysisCalls === 2) {
          return response({}, false);
        }
        return response({
          ...EMPTY_ANALYSIS,
          assessments: [assessment],
        });
      }
      return response({
        ...REPORT,
        assessments: [assessment],
      });
    }),
  );
  render(<SyntheticDemo />);

  await selectCustomAndRun();
  expect(
    await screen.findByRole("heading", {
      name: /synthetic flexibility fit demonstration/i,
    }),
  ).toBeVisible();

  await userEvent.click(
    screen.getByRole("button", { name: /run analysis/i }),
  );

  expect(
    await screen.findByText(/synthetic demonstration analysis failed/i),
  ).toBeVisible();
  expect(
    screen.queryByRole("heading", {
      name: /synthetic flexibility fit demonstration/i,
    }),
  ).not.toBeInTheDocument();
});

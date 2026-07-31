/* API client for the explicitly synthetic FlexCompass demonstration. */

import type {
  AnalyseResponse,
  DemoPortfolioListResponse,
  Portfolio,
  ReportResponse,
} from "./types";

const DEMO_BASE = "/api/demo";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

async function parseResponse<T>(
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

export async function fetchDemoPortfolios(): Promise<Portfolio[]> {
  const response = await fetch(`${DEMO_BASE}/portfolios`, {
    method: "GET",
  });
  const payload = await parseResponse<DemoPortfolioListResponse>(
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
  return parseResponse<AnalyseResponse>(
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
  return parseResponse<ReportResponse>(
    response,
    "Synthetic demonstration report generation failed",
  );
}

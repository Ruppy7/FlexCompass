/* API client for FlexCompass v0.1 */

import type { Portfolio, AnalyseResponse, ReportResponse, FlexZone, FlexSignal, PortalDataset, IngestStatus } from "./types";

const BASE = "/api";

// ---------------------------------------------------------------------------
// v0 endpoints
// ---------------------------------------------------------------------------

export async function fetchPortfolios(): Promise<Portfolio[]> {
  const res = await fetch(`${BASE}/portfolios`);
  if (!res.ok) throw new Error("Failed to fetch portfolios");
  return res.json();
}

export async function analysePortfolio(portfolio: Portfolio): Promise<AnalyseResponse> {
  const res = await fetch(`${BASE}/analyse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ portfolio }),
  });
  if (!res.ok) throw new Error("Analysis failed");
  return res.json();
}

export async function generateReport(portfolio: Portfolio): Promise<ReportResponse> {
  const res = await fetch(`${BASE}/report`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ portfolio }),
  });
  if (!res.ok) throw new Error("Report generation failed");
  return res.json();
}

// ---------------------------------------------------------------------------
// v0.1 endpoints
// ---------------------------------------------------------------------------

export async function fetchZones(dso?: string): Promise<FlexZone[]> {
  const url = dso ? `${BASE}/zones?dso=${dso}` : `${BASE}/zones`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch zones");
  const data = await res.json();
  // Backend returns paginated response: {items, total, limit, offset}
  return Array.isArray(data) ? data : (data.items || []);
}

export async function fetchSignals(): Promise<FlexSignal[]> {
  const res = await fetch(`${BASE}/signals`);
  if (!res.ok) throw new Error("Failed to fetch signals");
  const data = await res.json();
  // Backend returns paginated response: {items, total, limit, offset}
  return Array.isArray(data) ? data : (data.items || []);
}

export async function fetchPortalDatasets(): Promise<PortalDataset[]> {
  const res = await fetch(`${BASE}/portal/datasets`);
  if (!res.ok) throw new Error("Failed to fetch portal datasets");
  const data = await res.json();
  // Backend returns paginated response: {items, total, limit, offset}
  return Array.isArray(data) ? data : (data.items || []);
}

export async function fetchSignalsByZone(zoneId: string): Promise<FlexSignal[]> {
  const res = await fetch(`${BASE}/signals/by-zone/${zoneId}`);
  if (!res.ok) throw new Error("Failed to fetch signals for zone");
  return res.json();
}

export async function generateAssetGroup(spec: {
  asset_type: string;
  count: number;
  region: string;
}): Promise<{ asset_group: Record<string, unknown>; estimated_available_kw: number }> {
  const res = await fetch(`${BASE}/asset-groups/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(spec),
  });
  if (!res.ok) throw new Error("Failed to generate asset group");
  return res.json();
}

export async function fetchIngestStatus(): Promise<IngestStatus> {
  const res = await fetch(`${BASE}/ingest/status`);
  if (!res.ok) throw new Error("Failed to fetch ingest status");
  return res.json();
}

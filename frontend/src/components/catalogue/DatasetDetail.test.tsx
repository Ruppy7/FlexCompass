import { act, render, screen } from "@testing-library/react";
import { vi } from "vitest";

import {
  fetchCatalogueDataset,
  fetchCatalogueDatasetAssessments,
  fetchCatalogueDatasetEvidence,
  fetchCatalogueDatasetResources,
  fetchCatalogueObservations,
} from "@/lib/api";
import type { CatalogueDatasetDetail } from "@/lib/types";
import DatasetDetail from "./DatasetDetail";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    fetchCatalogueDataset: vi.fn(),
    fetchCatalogueDatasetResources: vi.fn(),
    fetchCatalogueDatasetEvidence: vi.fn(),
    fetchCatalogueDatasetAssessments: vi.fn(),
    fetchCatalogueObservations: vi.fn(),
  };
});

const DATASET: CatalogueDatasetDetail = {
  dataset_ref: "ssen:dataset-1",
  portal_id: "ssen",
  source_dataset_id: "dataset-1",
  title: "SSEN network dataset",
  description: null,
  publisher: null,
  licence: null,
  licence_identifier: null,
  licence_title: null,
  licence_url: null,
  attribution: null,
  themes: ["network"],
  catalogue_page_url: null,
  metadata_api_url: null,
  declared_update_frequency: null,
  declared_update_frequency_text: null,
  portal_url: null,
  api_url: null,
  source_created_at: null,
  source_updated_at: null,
  observed_at: "2026-08-03T12:00:00Z",
  lifecycle_status: "active",
  publication_pattern: "periodic",
  access_status: "public",
  tags: ["flexibility"],
};

const EMPTY_PAGE = { items: [], total: 0, limit: 50, offset: 0 };

function setSuccessfulChildren(): void {
  vi.mocked(fetchCatalogueDataset).mockResolvedValue(DATASET);
  vi.mocked(fetchCatalogueDatasetResources).mockResolvedValue({
    items: [{
      id: "resource-1",
      portal_id: "ssen",
      source_dataset_id: "dataset-1",
      name: "CSV resource",
      description: null,
      url: null,
      format: "CSV",
      media_type: null,
      size_bytes: null,
      source_created_at: null,
      source_updated_at: null,
      observed_at: null,
    }],
    total: 1,
    limit: 50,
    offset: 0,
  });
  vi.mocked(fetchCatalogueDatasetEvidence).mockResolvedValue(EMPTY_PAGE);
  vi.mocked(fetchCatalogueDatasetAssessments).mockResolvedValue({
    items: [{
      assessment_id: "assessment-1",
      observation_id: "observation-1",
      assessment_type: "maintenance_state",
      assessment_value: "on_schedule",
      confidence: "high",
      assessed_at: "2026-08-03T12:00:00Z",
    }],
    total: 1,
    limit: 50,
    offset: 0,
  });
  vi.mocked(fetchCatalogueObservations).mockResolvedValue({
    items: [{
      observation_id: "observation-1",
      portal_id: "ssen",
      observed_at: "2026-08-03T12:00:00Z",
      status: "complete",
      adapter_version: null,
      schema_version: 1,
      content_hash: null,
      expected_count: null,
      dataset_count: 1,
      resource_count: 1,
      complete: true,
    }],
    total: 1,
    limit: 50,
    offset: 0,
  });
}

it("renders safe metadata, children, observation identity, and Unknown nulls", async () => {
  setSuccessfulChildren();

  render(<DatasetDetail datasetRef="ssen:dataset-1" portalId="ssen" />);

  expect(await screen.findByText("SSEN network dataset")).toBeVisible();
  expect(screen.getByText(/CSV resource/)).toBeVisible();
  expect(screen.getByText("assessment-1")).toBeVisible();
  expect(screen.getByText("observation-1")).toBeVisible();
  expect(screen.getByRole("heading", { name: "Portal observation history" })).toBeVisible();
  expect(screen.getAllByText("Unknown").length).toBeGreaterThan(0);
  expect(fetchCatalogueObservations).toHaveBeenCalledWith(
    { portalId: "ssen", limit: 50, offset: 0 },
    expect.objectContaining({ signal: expect.any(AbortSignal) }),
  );
});

it("renders truthful empty child states", async () => {
  setSuccessfulChildren();
  vi.mocked(fetchCatalogueDatasetResources).mockResolvedValue(EMPTY_PAGE);
  vi.mocked(fetchCatalogueDatasetAssessments).mockResolvedValue(EMPTY_PAGE);
  vi.mocked(fetchCatalogueObservations).mockResolvedValue(EMPTY_PAGE);

  render(<DatasetDetail datasetRef="ssen:dataset-1" portalId="ssen" />);

  expect(await screen.findByText("No resources are available.")).toBeVisible();
  expect(screen.getByText("No evidence is available.")).toBeVisible();
  expect(screen.getByText("No assessments are available.")).toBeVisible();
  expect(screen.getByText("No observations are available.")).toBeVisible();
});

it("shows the latest real child failure without leaking stale content", async () => {
  setSuccessfulChildren();
  vi.mocked(fetchCatalogueDatasetEvidence).mockRejectedValue(
    new Error("Failed to fetch catalogue evidence"),
  );

  render(<DatasetDetail datasetRef="ssen:dataset-1" portalId="ssen" />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Failed to fetch catalogue evidence",
  );
  expect(screen.queryByText("SSEN network dataset")).not.toBeInTheDocument();
});

it("aborts replacement work and ignores a stale dataset response", async () => {
  let resolveFirst!: (value: CatalogueDatasetDetail) => void;
  let resolveSecond!: (value: CatalogueDatasetDetail) => void;
  vi.mocked(fetchCatalogueDataset)
    .mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve; }))
    .mockReturnValueOnce(new Promise((resolve) => { resolveSecond = resolve; }));
  vi.mocked(fetchCatalogueDatasetResources).mockResolvedValue(EMPTY_PAGE);
  vi.mocked(fetchCatalogueDatasetEvidence).mockResolvedValue(EMPTY_PAGE);
  vi.mocked(fetchCatalogueDatasetAssessments).mockResolvedValue(EMPTY_PAGE);
  vi.mocked(fetchCatalogueObservations).mockResolvedValue(EMPTY_PAGE);

  const { rerender } = render(
    <DatasetDetail datasetRef="ssen:first" portalId="ssen" />,
  );
  const firstSignal = vi.mocked(fetchCatalogueDataset).mock.calls[0][1]?.signal;
  rerender(<DatasetDetail datasetRef="ssen:second" portalId="ssen" />);

  expect(firstSignal?.aborted).toBe(true);
  await act(async () => {
    resolveSecond({ ...DATASET, dataset_ref: "ssen:second", title: "Newest dataset" });
  });
  expect(await screen.findByText("Newest dataset")).toBeVisible();

  await act(async () => {
    resolveFirst({ ...DATASET, dataset_ref: "ssen:first", title: "Stale dataset" });
  });
  expect(screen.queryByText("Stale dataset")).not.toBeInTheDocument();
});

it("aborts owned requests on unmount without displaying an abort error", () => {
  setSuccessfulChildren();

  const { unmount } = render(
    <DatasetDetail datasetRef="ssen:dataset-1" portalId="ssen" />,
  );
  const signal = vi.mocked(fetchCatalogueDataset).mock.calls[0][1]?.signal;
  unmount();

  expect(signal?.aborted).toBe(true);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";

import { fetchCatalogueDatasets } from "@/lib/api";
import type { CatalogueDatasetSummary, Page } from "@/lib/types";
import DatasetTable from "./DatasetTable";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, fetchCatalogueDatasets: vi.fn() };
});

vi.mock("./DatasetDetail", () => ({
  default: ({ datasetRef }: { datasetRef: string }) => (
    <div>Selected detail: {datasetRef}</div>
  ),
}));

const DATASET: CatalogueDatasetSummary = {
  dataset_ref: "ssen:dataset-1",
  portal_id: "ssen",
  source_dataset_id: "dataset-1",
  title: "SSEN dataset",
  description: null,
  publisher: null,
  licence: null,
  licence_identifier: null,
  licence_title: null,
  licence_url: null,
  attribution: null,
  themes: [],
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
  tags: [],
};

const EMPTY_PAGE: Page<CatalogueDatasetSummary> = {
  items: [], total: 0, limit: 20, offset: 0,
};

function datasetPage(
  dataset: CatalogueDatasetSummary,
  total = 1,
  offset = 0,
): Page<CatalogueDatasetSummary> {
  return { items: [dataset], total, limit: 20, offset };
}

beforeEach(() => {
  vi.mocked(fetchCatalogueDatasets).mockReset();
});

it("shows initial loading and then a truthful empty state", async () => {
  let resolve!: (page: Page<CatalogueDatasetSummary>) => void;
  vi.mocked(fetchCatalogueDatasets).mockReturnValue(
    new Promise((complete) => { resolve = complete; }),
  );

  render(<DatasetTable />);
  expect(screen.getByText("Loading datasets…")).toBeVisible();
  await act(async () => { resolve(EMPTY_PAGE); });

  expect(screen.getByText("No datasets match these filters.")).toBeVisible();
});

it("aborts replacement requests and ignores an older filter response", async () => {
  const user = userEvent.setup();
  let resolveNged!: (page: Page<CatalogueDatasetSummary>) => void;
  let resolveSsen!: (page: Page<CatalogueDatasetSummary>) => void;
  vi.mocked(fetchCatalogueDatasets)
    .mockResolvedValueOnce(EMPTY_PAGE)
    .mockReturnValueOnce(new Promise((resolve) => { resolveNged = resolve; }))
    .mockReturnValueOnce(new Promise((resolve) => { resolveSsen = resolve; }));
  render(<DatasetTable />);
  await screen.findByText("No datasets match these filters.");

  await user.selectOptions(screen.getByLabelText("Portal"), "nged");
  const ngedSignal = vi.mocked(fetchCatalogueDatasets).mock.calls[1][1]?.signal;
  await user.selectOptions(screen.getByLabelText("Portal"), "ssen");
  expect(ngedSignal?.aborted).toBe(true);

  await act(async () => {
    resolveSsen(datasetPage(DATASET));
  });
  expect(await screen.findByText("SSEN dataset")).toBeVisible();
  await act(async () => {
    resolveNged(datasetPage({
      ...DATASET,
      dataset_ref: "nged:stale",
      portal_id: "nged",
      title: "NGED stale dataset",
    }));
  });
  expect(screen.queryByText("NGED stale dataset")).not.toBeInTheDocument();
});

it("retains server filters across pagination and clears incompatible detail", async () => {
  const user = userEvent.setup();
  vi.mocked(fetchCatalogueDatasets).mockResolvedValue(
    datasetPage(DATASET, 25),
  );
  render(<DatasetTable />);
  await screen.findByText("SSEN dataset");

  await user.click(screen.getByRole("button", { name: "View SSEN dataset" }));
  expect(screen.getByText("Selected detail: ssen:dataset-1")).toBeVisible();
  await user.selectOptions(screen.getByLabelText("Portal"), "ssen");
  await user.type(screen.getByLabelText("Search datasets"), "network");
  await user.selectOptions(screen.getByLabelText("Maintenance"), "possibly_overdue");
  expect(screen.queryByText("Selected detail: ssen:dataset-1")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Next page" }));

  expect(fetchCatalogueDatasets).toHaveBeenLastCalledWith(
    expect.objectContaining({
      portalId: "ssen",
      query: "network",
      maintenance: "possibly_overdue",
      limit: 20,
      offset: 20,
    }),
    expect.objectContaining({ signal: expect.any(AbortSignal) }),
  );
});

it("uses response Page metadata to advance server pagination", async () => {
  const user = userEvent.setup();
  vi.mocked(fetchCatalogueDatasets).mockResolvedValue({
    items: [DATASET], total: 35, limit: 10, offset: 20,
  });
  render(<DatasetTable />);
  await screen.findByText("SSEN dataset");

  expect(screen.getByText("35 datasets · offset 20")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Next page" }));

  expect(fetchCatalogueDatasets).toHaveBeenLastCalledWith(
    expect.objectContaining({ limit: 20, offset: 30 }),
    expect.any(Object),
  );
});

it("shows the latest fixed dataset error and no legacy concepts", async () => {
  vi.mocked(fetchCatalogueDatasets).mockRejectedValue(
    new Error("Failed to fetch catalogue datasets"),
  );

  render(<DatasetTable />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Failed to fetch catalogue datasets",
  );
  expect(screen.queryByText(/zone|signal|ingested/i)).not.toBeInTheDocument();
});

it("aborts its current request on unmount", () => {
  vi.mocked(fetchCatalogueDatasets).mockReturnValue(new Promise(() => undefined));

  const { unmount } = render(<DatasetTable />);
  const signal = vi.mocked(fetchCatalogueDatasets).mock.calls[0][1]?.signal;
  unmount();

  expect(signal?.aborted).toBe(true);
});

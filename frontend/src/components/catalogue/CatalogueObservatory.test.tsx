import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";

import Home from "@/app/page";
import { fetchCataloguePortals, fetchDemoPortfolios } from "@/lib/api";
import type { CataloguePortalSummary, Page } from "@/lib/types";
import CatalogueObservatory from "./CatalogueObservatory";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    fetchCataloguePortals: vi.fn(),
    fetchDemoPortfolios: vi.fn(),
  };
});

vi.mock("./DatasetTable", () => ({
  default: () => <div>Dataset explorer</div>,
}));

const PORTAL: CataloguePortalSummary = {
  portal_id: "ssen",
  operator_name: "Scottish and Southern Electricity Networks",
  platform: "ckan",
  portal_url: null,
  current_attempt_status: "complete",
  current_attempt_at: "2026-08-03T12:00:00Z",
  current_attempt_warning_count: 0,
  operational_review_window_hours: 168,
  review_due_at: "2026-08-10T12:00:00Z",
  review_status: "current",
  last_complete_observation_id: "observation-1",
  last_complete_observed_at: "2026-08-03T12:00:00Z",
  latest_complete_snapshot_valid: true,
  latest_complete_validation_state: "valid",
  last_valid_observation_id: "observation-1",
  last_valid_observed_at: "2026-08-03T12:00:00Z",
  last_valid_dataset_count: 1,
  last_valid_resource_count: 2,
  degraded: false,
  snapshot_available: true,
};

const PORTAL_PAGE: Page<CataloguePortalSummary> = {
  items: [PORTAL], total: 1, limit: 50, offset: 0,
};

beforeEach(() => {
  vi.mocked(fetchCataloguePortals).mockReset();
  vi.mocked(fetchDemoPortfolios).mockResolvedValue([]);
});

it("shows initial coverage loading and renders the public portal page", async () => {
  let resolve!: (page: Page<CataloguePortalSummary>) => void;
  vi.mocked(fetchCataloguePortals).mockReturnValue(
    new Promise((complete) => { resolve = complete; }),
  );

  render(<CatalogueObservatory />);
  expect(screen.getByText("Loading portal coverage…")).toBeVisible();
  await act(async () => { resolve(PORTAL_PAGE); });

  expect(
    await screen.findByText("Scottish and Southern Electricity Networks"),
  ).toBeVisible();
});

it("provides keyboard accessible named inner tabs with selection and focus", async () => {
  const user = userEvent.setup();
  vi.mocked(fetchCataloguePortals).mockResolvedValue(PORTAL_PAGE);
  render(<CatalogueObservatory />);
  const coverage = screen.getByRole("tab", { name: "Coverage" });
  const datasets = screen.getByRole("tab", { name: "Datasets" });
  const panel = screen.getByRole("tabpanel");

  expect(coverage).toHaveAttribute("aria-controls", "catalogue-coverage-panel");
  expect(datasets).toHaveAttribute("aria-controls", "catalogue-datasets-panel");
  expect(panel).toHaveAttribute("id", "catalogue-coverage-panel");
  expect(panel).toHaveAttribute("aria-labelledby", "catalogue-coverage-tab");

  coverage.focus();
  await user.keyboard("{ArrowRight}");
  expect(datasets).toHaveFocus();
  expect(datasets).toHaveAttribute("aria-selected", "true");
  expect(await screen.findByText("Dataset explorer")).toBeVisible();
  await user.keyboard("{ArrowLeft}");
  expect(coverage).toHaveFocus();
  expect(coverage).toHaveAttribute("aria-selected", "true");
});

it("aborts coverage work when the nested tab changes and on unmount", async () => {
  const user = userEvent.setup();
  vi.mocked(fetchCataloguePortals).mockReturnValue(new Promise(() => undefined));
  const { unmount } = render(<CatalogueObservatory />);
  const signal = vi.mocked(fetchCataloguePortals).mock.calls[0][0]?.signal;

  await user.click(screen.getByRole("tab", { name: "Datasets" }));
  expect(signal?.aborted).toBe(true);
  unmount();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("preserves overview by default and the persistently labelled synthetic demo", async () => {
  const user = userEvent.setup();
  vi.mocked(fetchCataloguePortals).mockResolvedValue(PORTAL_PAGE);
  render(<Home />);

  expect(screen.getByRole("tab", { name: "Research Overview" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await user.click(screen.getByRole("tab", { name: "Synthetic Demo" }));
  expect(
    screen.getByText(/no live or current portal data is used/i),
  ).toBeVisible();
  expect(screen.getByRole("tab", { name: "Catalogue Observatory" })).toBeVisible();
});

it("supports ArrowLeft and ArrowRight on the named top-level tabs", async () => {
  const user = userEvent.setup();
  vi.mocked(fetchCataloguePortals).mockResolvedValue(PORTAL_PAGE);
  render(<Home />);
  const overview = screen.getByRole("tab", { name: "Research Overview" });
  const catalogue = screen.getByRole("tab", { name: "Catalogue Observatory" });

  overview.focus();
  await user.keyboard("{ArrowRight}");
  expect(catalogue).toHaveFocus();
  expect(catalogue).toHaveAttribute("aria-selected", "true");
  expect(catalogue).toHaveAttribute("aria-controls", "main-catalogue-panel");
  expect(screen.getByRole("tabpanel", { name: "Catalogue Observatory" })).toHaveAttribute(
    "id",
    "main-catalogue-panel",
  );
  await user.keyboard("{ArrowLeft}");
  expect(overview).toHaveFocus();
  expect(overview).toHaveAttribute("aria-selected", "true");
});

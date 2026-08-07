import { render, screen } from "@testing-library/react";

import type { CataloguePortalSummary } from "@/lib/types";
import PortalCoverageGrid from "./PortalCoverageGrid";

const DEGRADED_PORTAL: CataloguePortalSummary = {
  portal_id: "ssen",
  operator_name: "Scottish and Southern Electricity Networks",
  platform: "ckan",
  portal_url: "https://example.test/ssen",
  current_attempt_status: "complete",
  current_attempt_at: "2026-07-30T12:00:00Z",
  current_attempt_warning_count: 1,
  operational_review_window_hours: 168,
  review_due_at: "2026-08-05T12:00:00Z",
  review_status: "overdue",
  last_complete_observation_id: "newest-invalid",
  last_complete_observed_at: "2026-07-30T12:00:00Z",
  latest_complete_snapshot_valid: false,
  latest_complete_validation_state: "invalid",
  last_valid_observation_id: "older-valid",
  last_valid_observed_at: "2026-07-29T12:00:00Z",
  last_valid_dataset_count: 12,
  last_valid_resource_count: 24,
  degraded: true,
  snapshot_available: true,
};

const FAILED_WITH_LAST_COMPLETE: CataloguePortalSummary = {
  ...DEGRADED_PORTAL,
  current_attempt_status: "failed",
  current_attempt_at: "2026-07-30T12:00:00Z",
  last_complete_observation_id: "older-valid",
  last_complete_observed_at: "2026-07-29T12:00:00Z",
  latest_complete_snapshot_valid: true,
  latest_complete_validation_state: "valid",
  last_valid_observation_id: "older-valid",
  last_valid_observed_at: "2026-07-29T12:00:00Z",
  degraded: false,
};

it("renders exactly seven configured portals", () => {
  render(<PortalCoverageGrid portals={[DEGRADED_PORTAL]} />);

  expect(screen.getAllByTestId("portal-coverage-card")).toHaveLength(7);
  expect(screen.getByText("National Grid Electricity Distribution")).toBeVisible();
  expect(screen.getByText("Scottish and Southern Electricity Networks")).toBeVisible();
  expect(screen.getByText("National Energy System Operator")).toBeVisible();
});

it("shows a failed refresh beside its distinct last complete observation", () => {
  render(<PortalCoverageGrid portals={[FAILED_WITH_LAST_COMPLETE]} />);

  expect(screen.getByText("Refresh failed")).toBeVisible();
  expect(screen.getByText("Latest attempt: 30 July 2026, 12:00 UTC")).toBeVisible();
  expect(screen.getByText("Last complete: 29 July 2026, 12:00 UTC")).toBeVisible();
  expect(screen.queryByText("Snapshot checksum invalid")).not.toBeInTheDocument();
});

it("shows an invalid newest complete beside older last-valid evidence", () => {
  render(<PortalCoverageGrid portals={[DEGRADED_PORTAL]} />);

  expect(screen.getByText("Refresh complete")).toBeVisible();
  expect(screen.getByText("Snapshot checksum invalid")).toBeVisible();
  expect(screen.getByText("Latest attempt: 30 July 2026, 12:00 UTC")).toBeVisible();
  expect(screen.getByText("Last complete: 30 July 2026, 12:00 UTC")).toBeVisible();
  expect(screen.getByText("Last valid: 29 July 2026, 12:00 UTC")).toBeVisible();
  expect(screen.getByText("Datasets: 12")).toBeVisible();
  expect(screen.getByText("Resources: 24")).toBeVisible();
});

it("renders missing public facts as Unknown without inventing counts", () => {
  render(<PortalCoverageGrid portals={[]} />);

  expect(screen.getAllByText("Latest attempt: Unknown")).toHaveLength(7);
  expect(screen.getAllByText("Datasets: Unknown")).toHaveLength(7);
  expect(screen.getAllByText("Resources: Unknown")).toHaveLength(7);
});

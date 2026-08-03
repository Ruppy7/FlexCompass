import { render, screen } from "@testing-library/react";

import type { CatalogueObservation } from "@/lib/types";
import ObservationHistory from "./ObservationHistory";

const OBSERVATION: CatalogueObservation = {
  observation_id: "observation-1",
  portal_id: "ssen",
  observed_at: "2026-08-03T12:00:00Z",
  status: "partial",
  adapter_version: null,
  schema_version: null,
  content_hash: null,
  expected_count: null,
  dataset_count: 8,
  resource_count: null,
  complete: false,
};

it("shows safe observation identity and Unknown for null facts", () => {
  render(<ObservationHistory observations={[OBSERVATION]} />);

  expect(screen.getByText("observation-1")).toBeVisible();
  expect(screen.getByText("Partial")).toBeVisible();
  expect(screen.getAllByText("Unknown").length).toBeGreaterThan(0);
  expect(screen.getByText("8")).toBeVisible();
});

it("shows a truthful empty state", () => {
  render(<ObservationHistory observations={[]} />);

  expect(screen.getByText("No observations are available.")).toBeVisible();
});

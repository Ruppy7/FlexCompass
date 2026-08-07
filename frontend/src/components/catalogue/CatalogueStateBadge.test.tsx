import { render, screen } from "@testing-library/react";

import CatalogueStateBadge from "./CatalogueStateBadge";

it.each([
  ["unknown", "Unknown"],
  ["restricted", "Restricted"],
  ["unreachable", "Unreachable"],
  ["historical_archive", "Historical archive"],
  ["possibly_overdue", "Possibly overdue"],
  ["never_attempted", "Never attempted"],
])("renders %s as visible text", (state, label) => {
  render(<CatalogueStateBadge state={state} />);

  expect(screen.getByText(label)).toBeVisible();
});

import { render, screen } from "@testing-library/react";
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

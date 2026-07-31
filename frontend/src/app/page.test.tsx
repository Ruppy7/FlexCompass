import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import Home from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

function mockFetch(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise(() => undefined)),
  );
}

it("defaults to research overview without the synthetic form", () => {
  mockFetch();
  render(<Home />);
  expect(
    screen.getByRole("heading", { name: /research status/i }),
  ).toBeVisible();
  expect(
    screen.queryByText(/portfolio input/i),
  ).not.toBeInTheDocument();
});

it("labels the synthetic demonstration persistently", async () => {
  mockFetch();
  render(<Home />);
  await userEvent.click(
    screen.getByRole("tab", { name: /synthetic demo/i }),
  );
  expect(
    screen.getByText(/no live or current portal data is used/i),
  ).toBeVisible();
});

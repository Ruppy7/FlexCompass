import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import PortfolioForm from "./PortfolioForm";

it("submits every custom asset with an explicit synthetic source", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        workflow_kind: "synthetic_demo",
        portal_data_used: false,
        items: [],
      }),
    }),
  );
  const onAnalyse = vi.fn();
  render(<PortfolioForm onAnalyse={onAnalyse} loading={false} />);

  await userEvent.click(
    screen.getByRole("button", { name: /custom portfolio/i }),
  );
  await userEvent.click(
    screen.getByRole("button", { name: /run analysis/i }),
  );

  expect(onAnalyse).toHaveBeenCalledWith(
    expect.objectContaining({
      assets: [
        expect.objectContaining({ source: "synthetic" }),
      ],
    }),
  );
});

it("labels and constrains availability as a zero-to-one fraction", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise(() => undefined)),
  );
  render(<PortfolioForm onAnalyse={vi.fn()} loading={false} />);
  await userEvent.click(
    screen.getByRole("button", { name: /custom portfolio/i }),
  );

  const availability = screen.getByRole("spinbutton", {
    name: /availability fraction.*0.*1/i,
  });
  expect(availability).toHaveAttribute("min", "0");
  expect(availability).toHaveAttribute("max", "1");
  expect(availability).toHaveAttribute("step", "0.01");
});

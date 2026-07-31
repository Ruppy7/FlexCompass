import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import PortfolioForm from "./PortfolioForm";

it("submits every custom asset with an explicit synthetic source", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [] }),
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

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import ReportView from "./ReportView";

it("defaults to the meaningful Markdown report when assessments are empty", () => {
  render(
    <ReportView
      markdown={[
        "# Synthetic Flexibility Fit Demonstration",
        "",
        "No public flexibility signals were considered.",
      ].join("\n")}
      assessments={[]}
      signals={[]}
    />,
  );

  expect(
    screen.getByText(/no public flexibility signals were considered/i),
  ).toBeVisible();
  expect(
    screen.getByRole("heading", {
      name: /synthetic flexibility fit demonstration/i,
      level: 1,
    }),
  ).toBeVisible();
});

it("downloads only the labelled synthetic report filename", async () => {
  vi.stubGlobal("fetch", vi.fn());
  vi.stubGlobal(
    "URL",
    {
      createObjectURL: vi.fn(() => "blob:synthetic-report"),
      revokeObjectURL: vi.fn(),
    },
  );
  let downloadName = "";
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
    function captureDownload(this: HTMLAnchorElement) {
      downloadName = this.download;
    },
  );

  render(
    <ReportView
      markdown="# Synthetic Flexibility Fit Demonstration"
      assessments={[]}
      signals={[]}
    />,
  );
  await userEvent.click(
    screen.getByRole("button", { name: /download/i }),
  );

  expect(downloadName).toBe("flexcompass-synthetic-demo.md");
});

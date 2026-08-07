"use client";

import { KeyboardEvent, useRef, useState } from "react";

import PortalIntelligence from "@/components/PortalIntelligence";
import ResearchOverview from "@/components/ResearchOverview";
import SyntheticDemo from "@/components/SyntheticDemo";

type Tab = "overview" | "catalogue" | "synthetic_demo";

const TABS: { key: Tab; label: string }[] = [
  { key: "overview", label: "Research Overview" },
  { key: "catalogue", label: "Catalogue Observatory" },
  { key: "synthetic_demo", label: "Synthetic Demo" },
];

export default function Home() {
  const [tab, setTab] = useState<Tab>("overview");
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const selectTab = (next: Tab, index: number) => {
    setTab(next);
    queueMicrotask(() => tabRefs.current[index]?.focus());
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const nextIndex = (index + direction + TABS.length) % TABS.length;
    selectTab(TABS[nextIndex].key, nextIndex);
  };

  return (
    <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
      <header className="mb-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-gray-900">
              FlexCompass
            </h1>
            <p className="text-sm text-gray-500 mt-0.5">
              Open-source GB grid-data research toolkit
            </p>
          </div>
          <span className="text-xs font-medium text-brand-700 bg-brand-50 px-3 py-1 rounded-full">
            v0.1
          </span>
        </div>
      </header>

      <div
        role="tablist"
        aria-label="Main sections"
        className="flex gap-1 mb-6 border-b border-gray-200"
      >
        {TABS.map(({ key, label }, index) => (
          <button
            key={key}
            id={`main-${key}-tab`}
            aria-controls={`main-${key}-panel`}
            ref={(element) => { tabRefs.current[index] = element; }}
            type="button"
            role="tab"
            aria-selected={tab === key}
            tabIndex={tab === key ? 0 : -1}
            onClick={() => setTab(key)}
            onKeyDown={(event) => handleKeyDown(event, index)}
            className={`px-5 py-3 text-sm font-medium border-b-2 ${
              tab === key
                ? "border-brand-600 text-brand-700"
                : "border-transparent text-gray-500"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div
        role="tabpanel"
        id={`main-${tab}-panel`}
        aria-labelledby={`main-${tab}-tab`}
      >
        {tab === "overview" && <ResearchOverview />}
        {tab === "catalogue" && <PortalIntelligence />}
        {tab === "synthetic_demo" && <SyntheticDemo />}
      </div>

      <footer className="text-center text-xs text-gray-400 py-6 mt-8 border-t border-gray-200">
        FlexCompass v0.1 · Independent public-data research · Synthetic
        demonstration clearly labelled · Not a bid recommendation tool
      </footer>
    </main>
  );
}

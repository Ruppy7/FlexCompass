"use client";

import { useState } from "react";

import ResearchOverview from "@/components/ResearchOverview";
import SyntheticDemo from "@/components/SyntheticDemo";

type Tab = "overview" | "synthetic_demo";

const TABS: { key: Tab; label: string }[] = [
  { key: "overview", label: "Research Overview" },
  { key: "synthetic_demo", label: "Synthetic Demo" },
];

export default function Home() {
  const [tab, setTab] = useState<Tab>("overview");

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
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
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

      {tab === "overview" && <ResearchOverview />}
      {tab === "synthetic_demo" && <SyntheticDemo />}

      <footer className="text-center text-xs text-gray-400 py-6 mt-8 border-t border-gray-200">
        FlexCompass v0.1 · Independent public-data research · Synthetic
        demonstration clearly labelled · Not a bid recommendation tool
      </footer>
    </main>
  );
}

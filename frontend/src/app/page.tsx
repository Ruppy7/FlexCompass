"use client";

import { useState } from "react";
import type { Portfolio, FitAssessment, FlexSignal, ReportResponse } from "@/lib/types";
import { fetchSignals, generateReport } from "@/lib/api";
import PortfolioForm from "@/components/PortfolioForm";
import ReportView from "@/components/ReportView";
import PortalIntelligence from "@/components/PortalIntelligence";
import ErrorBanner from "@/components/ui/ErrorBanner";

type Tab = "intelligence" | "analysis";

const TABS: { key: Tab; label: string }[] = [
  { key: "intelligence", label: "Portal Intelligence" },
  { key: "analysis", label: "Portfolio Analysis" },
];

export default function Home() {
  const [tab, setTab] = useState<Tab>("intelligence");
  const [assessments, setAssessments] = useState<FitAssessment[]>([]);
  const [signals, setSignals] = useState<FlexSignal[]>([]);
  const [reportMd, setReportMd] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasResult, setHasResult] = useState(false);

  const handleAnalyse = async (portfolio: Portfolio) => {
    setLoading(true);
    setError(null);
    try {
      const allSignals = await fetchSignals();
      setSignals(allSignals);
      const report: ReportResponse = await generateReport(portfolio);
      setAssessments(report.assessments);
      setReportMd(report.markdown);
      setHasResult(true);
      setTab("analysis");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
      {/* Header */}
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
        <p className="text-xs text-gray-400 mt-2">
          Public network data · Provenance-preserving models · Heuristic &amp;
          directional analysis
        </p>
      </header>

      {/* Navigation tabs */}
      <div
        role="tablist"
        aria-label="Main sections"
        className="flex gap-1 mb-6 border-b border-gray-200"
      >
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`px-5 py-3 text-sm font-medium border-b-2 transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 ${
              tab === key
                ? "border-brand-600 text-brand-700"
                : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "intelligence" && <PortalIntelligence />}

      {tab === "analysis" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-1">
            <PortfolioForm onAnalyse={handleAnalyse} loading={loading} />
          </div>
          <div className="lg:col-span-2">
            {error && (
              <div className="mb-4">
                <ErrorBanner message={error} />
              </div>
            )}
            {!hasResult && !loading && (
              <div className="bg-surface rounded-lg shadow-card p-8 text-center text-gray-500 animate-fade-in">
                <div className="text-4xl mb-3 opacity-30">⚡</div>
                <p className="text-base font-medium mb-1">
                  Select or create a portfolio, then run analysis.
                </p>
                <p className="text-sm text-gray-400">
                  The report will show which public flexibility-market signals may be
                  worth investigating for your DER portfolio.
                </p>
              </div>
            )}
            {loading && (
              <div className="bg-surface rounded-lg shadow-card p-8 text-center animate-fade-in">
                <div className="animate-spin inline-block w-8 h-8 border-[3px] border-brand-600 border-t-transparent rounded-full mb-4" />
                <p className="text-sm text-gray-600">
                  Running heuristic matching analysis…
                </p>
              </div>
            )}
            {hasResult && !loading && (
              <div className="animate-slide-up">
                <ReportView
                  markdown={reportMd}
                  assessments={assessments}
                  signals={signals}
                />
              </div>
            )}
          </div>
        </div>
      )}

      {/* Footer */}
      <footer className="text-center text-xs text-gray-400 py-6 mt-8 border-t border-gray-200">
        FlexCompass v0.1 · Independent public-data research · Heuristic &amp;
        directional · Not a bid recommendation tool
      </footer>
    </main>
  );
}

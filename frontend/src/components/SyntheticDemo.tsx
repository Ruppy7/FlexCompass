"use client";

import { useState } from "react";

import {
  analyseDemoPortfolio,
  generateDemoReport,
} from "@/lib/api";
import type { FitAssessment, Portfolio } from "@/lib/types";
import ErrorBanner from "@/components/ui/ErrorBanner";
import PortfolioForm from "./PortfolioForm";
import ReportView from "./ReportView";

export default function SyntheticDemo() {
  const [assessments, setAssessments] = useState<FitAssessment[]>([]);
  const [reportMarkdown, setReportMarkdown] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAnalyse = async (portfolio: Portfolio) => {
    setLoading(true);
    setError(null);
    try {
      const [analysis, report] = await Promise.all([
        analyseDemoPortfolio(portfolio),
        generateDemoReport(portfolio),
      ]);
      setAssessments(analysis.assessments);
      setReportMarkdown(report.markdown);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Synthetic demonstration failed",
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="space-y-6">
      <div
        role="status"
        className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm font-medium text-amber-900"
      >
        Synthetic demonstration — no live or current portal data is used.
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div>
          <PortfolioForm
            onAnalyse={handleAnalyse}
            loading={loading}
          />
        </div>
        <div className="lg:col-span-2">
          {error && <ErrorBanner message={error} />}
          {!reportMarkdown && !loading && (
            <div className="bg-surface rounded-lg shadow-card p-8 text-center text-gray-500">
              Build a synthetic scenario to explore the demonstration.
            </div>
          )}
          {loading && (
            <div className="bg-surface rounded-lg shadow-card p-8 text-center text-gray-600">
              Running synthetic demonstration…
            </div>
          )}
          {reportMarkdown && !loading && (
            <ReportView
              markdown={reportMarkdown}
              assessments={assessments}
              signals={[]}
            />
          )}
        </div>
      </div>
    </section>
  );
}

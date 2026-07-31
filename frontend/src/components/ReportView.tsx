"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import type { FitAssessment, FlexSignal } from "@/lib/types";
import SignalCard from "./SignalCard";

interface Props {
  markdown: string;
  assessments: FitAssessment[];
  signals: FlexSignal[];
}

export default function ReportView({ markdown, assessments, signals }: Props) {
  const [view, setView] = useState<"cards" | "markdown">(
    assessments.length === 0 ? "markdown" : "cards",
  );
  const signalMap = new Map(signals.map((s) => [s.signal_id, s]));

  const copyToClipboard = () => {
    navigator.clipboard.writeText(markdown);
  };

  const downloadMarkdown = () => {
    const blob = new Blob([markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "flexcompass-synthetic-demo.md";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="bg-surface rounded-lg shadow-card p-6">
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-bold text-gray-900">
          Synthetic Flexibility Fit Demonstration
        </h2>
        <div className="flex gap-1 bg-surface-muted rounded-lg p-0.5">
          <button
            onClick={() => setView("cards")}
            className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors duration-150 ${
              view === "cards" ? "bg-surface text-brand-700 shadow-sm" : "text-gray-500 hover:text-gray-700"
            }`}
          >
            Cards
          </button>
          <button
            onClick={() => setView("markdown")}
            className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors duration-150 ${
              view === "markdown" ? "bg-surface text-brand-700 shadow-sm" : "text-gray-500 hover:text-gray-700"
            }`}
          >
            Markdown
          </button>
        </div>
      </div>

      {/* Export buttons */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={copyToClipboard}
          className="text-sm px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-surface-muted transition-colors duration-150 text-gray-600"
        >
          📋 Copy
        </button>
        <button
          onClick={downloadMarkdown}
          className="text-sm px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-surface-muted transition-colors duration-150 text-gray-600"
        >
          ⬇️ Download .md
        </button>
      </div>

      {view === "cards" ? (
        <div className="space-y-3">
          {assessments.map((a, i) => (
            <SignalCard
              key={a.signal_id}
              assessment={a}
              signal={signalMap.get(a.signal_id)}
              rank={i + 1}
            />
          ))}
        </div>
      ) : (
        <div className="prose prose-sm max-w-none border border-gray-200 rounded-lg p-4 bg-surface-muted overflow-auto max-h-[600px]">
          <ReactMarkdown>{markdown}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}

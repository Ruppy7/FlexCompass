"use client";

import type { FitAssessment, FlexSignal } from "@/lib/types";

interface Props {
  assessment: FitAssessment;
  signal?: FlexSignal;
  rank: number;
}

const BAND_STYLES: Record<string, string> = {
  high: "border-success-400 bg-success-50",
  medium: "border-warning-400 bg-warning-50",
  low: "border-gray-300 bg-gray-50",
  insufficient_evidence: "border-gray-200 bg-surface-muted",
};

const BAND_LABELS: Record<string, string> = {
  high: "High Priority",
  medium: "Medium Priority",
  low: "Low Priority",
  insufficient_evidence: "Insufficient Evidence",
};

const BAND_DOTS: Record<string, string> = {
  high: "bg-success-500",
  medium: "bg-warning-500",
  low: "bg-gray-400",
  insufficient_evidence: "bg-gray-300",
};

const CHECKS: [string, keyof FitAssessment][] = [
  ["Geography", "location_evidence"],
  ["Asset Type", "asset_type_compatibility"],
  ["Capacity", "capacity_plausibility"],
  ["Temporal", "temporal_feasibility"],
  ["Market Rule", "market_rule_clarity"],
  ["Data Quality", "data_completeness"],
  ["Ops Complexity", "operational_complexity"],
];

export default function SignalCard({ assessment, signal, rank }: Props) {
  const band = assessment.investigation_priority_band;

  return (
    <div className={`border-l-4 rounded-lg p-5 ${BAND_STYLES[band]} shadow-card transition-shadow duration-150 hover:shadow-card-hover`}>
      <div className="flex justify-between items-start mb-3">
        <h3 className="font-bold text-gray-900">
          <span className="text-gray-400 font-normal mr-1.5">#{rank}</span>
          {signal ? `${signal.dso} — ${signal.area_name}` : assessment.signal_id}
        </h3>
        <span className="flex items-center gap-1.5 text-sm font-semibold px-2.5 py-1 rounded-full bg-surface shadow-sm whitespace-nowrap">
          <span className={`w-2 h-2 rounded-full ${BAND_DOTS[band]}`} />
          {BAND_LABELS[band]}
        </span>
      </div>

      {signal && (
        <div className="text-sm text-gray-600 mb-3 flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-medium capitalize">
            {signal.service_type.replace(/_/g, " ")}
          </span>
          <span className="text-gray-300">·</span>
          <span className="capitalize">{signal.procurement_type}</span>
          {signal.capacity_kw && (
            <>
              <span className="text-gray-300">·</span>
              <span>{signal.capacity_kw.toLocaleString()} kW</span>
            </>
          )}
          {signal.guide_price && signal.price_unit && (
            <>
              <span className="text-gray-300">·</span>
              <span>£{signal.guide_price} {signal.price_unit}</span>
            </>
          )}
        </div>
      )}

      <div className="text-sm mb-3">
        <span className="font-medium text-gray-700">Est. Available:</span>{" "}
        <span className="font-semibold text-gray-900">
          {assessment.estimated_available_kw.toLocaleString(undefined, { maximumFractionDigits: 1 })} kW
        </span>
      </div>

      {/* Check results grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs mb-3">
        {CHECKS.map(([label, key]) => (
          <div key={label} className="bg-surface rounded-md px-2.5 py-1.5 border border-gray-100">
            <span className="text-gray-400">{label}</span>{" "}
            <span className="font-medium text-gray-700 capitalize">
              {String(assessment[key]).replace(/_/g, " ")}
            </span>
          </div>
        ))}
      </div>

      {/* Risks */}
      {assessment.risk_flags.length > 0 && (
        <div className="text-xs mb-2">
          <span className="font-semibold text-danger-700">Risks:</span>
          <ul className="list-disc ml-4 text-danger-600 mt-1 space-y-0.5">
            {assessment.risk_flags.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

import { render, screen } from "@testing-library/react";

import type { FitAssessment, FlexSignal } from "@/lib/types";
import SignalCard from "./SignalCard";

const ASSESSMENT: FitAssessment = {
  assessment_id: "assessment-null-evidence",
  portfolio_id: "portfolio-1",
  signal_id: "signal-null-evidence",
  estimated_available_kw: 0,
  investigation_priority_band: "insufficient_evidence",
  investigation_priority_score_optional: null,
  location_evidence: "unknown",
  asset_type_compatibility: "unclear",
  capacity_plausibility: "unknown",
  temporal_feasibility: "unknown",
  market_rule_clarity: "unknown",
  data_completeness: "low",
  operational_complexity: "unknown",
  evidence_summary: [],
  missing_information: [],
  risk_flags: [],
  next_steps: [],
  disclaimer: "Synthetic demonstration.",
};

const NULLABLE_SIGNAL: FlexSignal = {
  signal_id: "signal-null-evidence",
  zone_id: null,
  source_id: null,
  dso: "NGED",
  platform: null,
  market_name: null,
  area_name: null,
  location_type: null,
  location_reference: null,
  service_type: null,
  direction: null,
  requirement_type: null,
  tender_round: null,
  historic_current_future_status: "unknown",
  procurement_type: null,
  window_start: null,
  window_end: null,
  duration_minutes: null,
  lead_time: null,
  capacity_kw: null,
  guide_price: null,
  price_unit: null,
  utilisation_estimate: null,
  payment_type: null,
  eligible_asset_types: null,
  source_updated_at: null,
  source_dataset_id: null,
  raw_record: null,
  confidence_level: "unknown",
  missing_fields: [],
  data_quality_notes: [],
};

it("renders nullable signal evidence explicitly as unknown", () => {
  render(
    <SignalCard
      assessment={ASSESSMENT}
      signal={NULLABLE_SIGNAL}
      rank={1}
    />,
  );

  expect(
    screen.getByRole("heading", { name: /NGED.*Unknown/i }),
  ).toBeVisible();
  expect(screen.getAllByText("Unknown")).toHaveLength(2);
  expect(screen.queryByText(/null/i)).not.toBeInTheDocument();
});

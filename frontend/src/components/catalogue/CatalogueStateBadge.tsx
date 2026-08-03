const LABELS: Record<string, string> = {
  active: "Active",
  closed_period: "Closed period",
  complete: "Complete",
  continuous: "Continuous",
  current: "Current",
  event_driven: "Event driven",
  expected_dormant: "Expected dormant",
  failed: "Failed",
  historical_archive: "Historical archive",
  invalid: "Invalid",
  never_attempted: "Never attempted",
  on_schedule: "On schedule",
  overdue: "Overdue",
  partial: "Partial",
  periodic: "Periodic",
  possibly_overdue: "Possibly overdue",
  public: "Public",
  registered: "Registered",
  restricted: "Restricted",
  retired: "Retired",
  stale: "Stale",
  static_reference: "Static reference",
  superseded: "Superseded",
  unavailable: "Unavailable",
  unknown: "Unknown",
  unreachable: "Unreachable",
  valid: "Valid",
};

interface CatalogueStateBadgeProps {
  state: string | null | undefined;
}

export default function CatalogueStateBadge({ state }: CatalogueStateBadgeProps) {
  const label = state ? LABELS[state] ?? state.replaceAll("_", " ") : "Unknown";
  return (
    <span className="inline-flex rounded-full bg-gray-100 px-2 py-1 text-xs font-medium text-gray-800">
      {label}
    </span>
  );
}

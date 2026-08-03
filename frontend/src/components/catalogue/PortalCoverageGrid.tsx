import type { CataloguePortalId, CataloguePortalSummary } from "@/lib/types";
import CatalogueStateBadge from "./CatalogueStateBadge";

const PORTALS: { id: CataloguePortalId; name: string }[] = [
  { id: "nged", name: "National Grid Electricity Distribution" },
  { id: "spen", name: "SP Energy Networks" },
  { id: "enwl", name: "Electricity North West" },
  { id: "ssen", name: "Scottish and Southern Electricity Networks" },
  { id: "ukpn", name: "UK Power Networks" },
  { id: "npg", name: "Northern Powergrid" },
  { id: "neso", name: "National Energy System Operator" },
];

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  const parts = new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) => (
    parts.find((candidate) => candidate.type === type)?.value ?? ""
  );
  return `${part("day")} ${part("month")} ${part("year")}, ${part("hour")}:${part("minute")} UTC`;
}

function attemptLabel(status: string | null): string {
  if (status === "failed") return "Refresh failed";
  if (status === "partial") return "Partial refresh";
  if (status === "complete") return "Refresh complete";
  return "Refresh status Unknown";
}

function validationLabel(state: CataloguePortalSummary["latest_complete_validation_state"]): string {
  if (state === "invalid") return "Snapshot checksum invalid";
  if (state === "valid") return "Snapshot valid";
  return "Snapshot unavailable";
}

interface PortalCoverageGridProps {
  portals: CataloguePortalSummary[];
}

export default function PortalCoverageGrid({ portals }: PortalCoverageGridProps) {
  const byId = new Map(portals.map((portal) => [portal.portal_id, portal]));
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {PORTALS.map(({ id, name }) => {
        const portal = byId.get(id);
        return (
          <article key={id} data-testid="portal-coverage-card" className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex items-start justify-between gap-2">
              <div><h3 className="font-semibold text-gray-900">{portal?.operator_name ?? name}</h3><p className="text-xs uppercase text-gray-500">{id}</p></div>
              <CatalogueStateBadge state={portal?.review_status} />
            </div>
            <div className="mt-3 space-y-1 text-sm text-gray-700">
              <p className="font-medium">{portal ? attemptLabel(portal.current_attempt_status) : "Refresh status Unknown"}</p>
              <p>{portal ? validationLabel(portal.latest_complete_validation_state) : "Snapshot unavailable"}</p>
              <p>Latest attempt: {formatTimestamp(portal?.current_attempt_at)}</p>
              <p>Review due: {formatTimestamp(portal?.review_due_at)}</p>
              <p>Last complete: {formatTimestamp(portal?.last_complete_observed_at)}</p>
              <p>Last valid: {formatTimestamp(portal?.last_valid_observed_at)}</p>
              <p>Datasets: {portal ? portal.last_valid_dataset_count : "Unknown"}</p>
              <p>Resources: {portal ? portal.last_valid_resource_count : "Unknown"}</p>
              <p>Warnings: {portal ? portal.current_attempt_warning_count : "Unknown"}</p>
              <p>Snapshot available: {portal ? (portal.snapshot_available ? "Yes" : "No") : "Unknown"}</p>
              <p>Degraded: {portal ? (portal.degraded ? "Yes" : "No") : "Unknown"}</p>
            </div>
          </article>
        );
      })}
    </div>
  );
}

import type { CatalogueObservation } from "@/lib/types";
import CatalogueStateBadge from "./CatalogueStateBadge";

interface ObservationHistoryProps {
  observations: CatalogueObservation[];
}

function valueOrUnknown(value: string | number | null): string | number {
  return value ?? "Unknown";
}

export default function ObservationHistory({ observations }: ObservationHistoryProps) {
  if (observations.length === 0) {
    return <p className="text-sm text-gray-600">No observations are available.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <thead><tr className="border-b"><th>Observation</th><th>Status</th><th>Observed</th><th>Schema</th><th>Datasets</th><th>Resources</th></tr></thead>
        <tbody>
          {observations.map((observation) => (
            <tr key={observation.observation_id} className="border-b">
              <td className="py-2 pr-3 font-mono text-xs">{observation.observation_id}</td>
              <td className="py-2 pr-3"><CatalogueStateBadge state={observation.status} /></td>
              <td className="py-2 pr-3">{valueOrUnknown(observation.observed_at)}</td>
              <td className="py-2 pr-3">{valueOrUnknown(observation.schema_version)}</td>
              <td className="py-2 pr-3">{valueOrUnknown(observation.dataset_count)}</td>
              <td className="py-2">{valueOrUnknown(observation.resource_count)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

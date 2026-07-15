import Badge from "@/components/ui/Badge";
import type { FlexZone } from "@/lib/types";

interface ZonesTabProps {
  zones: FlexZone[];
}

export default function ZonesTab({ zones }: ZonesTabProps) {
  const byDso = zones.reduce<Record<string, number>>((acc, z) => {
    acc[z.dso] = (acc[z.dso] || 0) + 1;
    return acc;
  }, {});

  return (
    <div>
      <div className="flex flex-wrap gap-2 mb-4">
        {Object.entries(byDso).map(([dso, count]) => (
          <Badge key={dso} variant="dso" dso={dso} className="px-3 py-1 text-sm">
            {dso}: {count} zones
          </Badge>
        ))}
      </div>

      {/* Desktop table */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-gray-500">
              <th className="py-2 pr-4">Zone ID</th>
              <th className="py-2 pr-4">DSO</th>
              <th className="py-2 pr-4">Area</th>
              <th className="py-2 pr-4">Type</th>
              <th className="py-2">Prefixes</th>
            </tr>
          </thead>
          <tbody>
            {zones.map((z) => (
              <tr key={z.zone_id} className="border-b hover:bg-gray-50">
                <td className="py-3 pr-4 font-mono text-xs">{z.zone_id}</td>
                <td className="py-3 pr-4">
                  <Badge variant="dso" dso={z.dso} />
                </td>
                <td className="py-3 pr-4">{z.area_name}</td>
                <td className="py-3 pr-4 text-gray-500">{z.zone_type}</td>
                <td className="py-3 text-xs text-gray-400">
                  {z.postcode_prefixes.join(", ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile cards */}
      <div className="md:hidden space-y-3">
        {zones.map((z) => (
          <div
            key={z.zone_id}
            className="border rounded-lg p-3 bg-surface-muted"
          >
            <div className="flex items-start justify-between gap-2 mb-2">
              <span className="font-mono text-xs text-gray-700 break-all">
                {z.zone_id}
              </span>
              <Badge variant="dso" dso={z.dso} />
            </div>
            <p className="text-sm font-medium text-gray-900">{z.area_name}</p>
            <p className="text-xs text-gray-500 mt-1">{z.zone_type}</p>
            {z.postcode_prefixes.length > 0 && (
              <p className="text-xs text-gray-400 mt-2 break-words">
                {z.postcode_prefixes.join(", ")}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

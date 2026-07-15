import Badge from "@/components/ui/Badge";
import type { PortalDataset } from "@/lib/types";

interface DatasetsTabProps {
  datasets: PortalDataset[];
}

export default function DatasetsTab({ datasets }: DatasetsTabProps) {
  return (
    <div className="space-y-4">
      {datasets.map((d) => (
        <div key={d.id} className="border rounded-lg p-4">
          <div className="flex items-start justify-between gap-2 mb-2">
            <div className="min-w-0">
              <h3 className="font-semibold text-gray-900">{d.name}</h3>
              <p className="text-xs text-gray-400 font-mono break-all">{d.id}</p>
            </div>
            {d.record_count && (
              <Badge variant="neutral">
                {d.record_count.toLocaleString()} records
              </Badge>
            )}
          </div>
          <a
            href={d.portal_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-brand-600 hover:underline break-all"
          >
            {d.portal_url}
          </a>
          {d.fields.length > 0 && (
            <div className="mt-2">
              <p className="text-xs text-gray-500 mb-1">Fields:</p>
              <div className="flex flex-wrap gap-1">
                {d.fields.map((f) => (
                  <span
                    key={f}
                    className="bg-brand-50 text-brand-700 px-2 py-0.5 rounded text-xs"
                  >
                    {f}
                  </span>
                ))}
              </div>
            </div>
          )}
          {d.limitations.length > 0 && (
            <div className="mt-2">
              <p className="text-xs text-gray-500 mb-1">Limitations:</p>
              <ul className="text-xs text-gray-600 list-disc list-inside space-y-0.5">
                {d.limitations.map((l, i) => (
                  <li key={i}>{l}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

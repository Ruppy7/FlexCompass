import Badge from "@/components/ui/Badge";
import type { FlexSignal } from "@/lib/types";

interface SignalsTabProps {
  signals: FlexSignal[];
}

export default function SignalsTab({ signals }: SignalsTabProps) {
  return (
    <div>
      {/* Desktop table */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-gray-500">
              <th className="py-2 pr-4">Signal</th>
              <th className="py-2 pr-4">DSO</th>
              <th className="py-2 pr-4">Area</th>
              <th className="py-2 pr-4">Service</th>
              <th className="py-2 pr-4">Capacity</th>
              <th className="py-2 pr-4">Price</th>
              <th className="py-2">Confidence</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((s) => (
              <tr key={s.signal_id} className="border-b hover:bg-gray-50">
                <td className="py-3 pr-4 font-mono text-xs max-w-[200px] truncate">
                  {s.signal_id}
                </td>
                <td className="py-3 pr-4">
                  <Badge variant="dso" dso={s.dso} />
                </td>
                <td className="py-3 pr-4">{s.area_name}</td>
                <td className="py-3 pr-4 text-xs">
                  {s.service_type.replace(/_/g, " ")}
                </td>
                <td className="py-3 pr-4">
                  {s.capacity_kw ? `${s.capacity_kw.toLocaleString()} kW` : "—"}
                </td>
                <td className="py-3 pr-4">
                  {s.guide_price ? `£${s.guide_price} ${s.price_unit || ""}` : "—"}
                </td>
                <td className="py-3">
                  <Badge variant="confidence" level={s.confidence_level} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile cards */}
      <div className="md:hidden space-y-3">
        {signals.map((s) => (
          <div
            key={s.signal_id}
            className="border rounded-lg p-3 bg-surface-muted"
          >
            <div className="flex items-start justify-between gap-2 mb-2">
              <span className="font-mono text-xs text-gray-700 break-all">
                {s.signal_id}
              </span>
              <Badge variant="dso" dso={s.dso} />
            </div>
            <p className="text-sm font-medium text-gray-900">{s.area_name}</p>
            <p className="text-xs text-gray-500 mt-1">
              {s.service_type.replace(/_/g, " ")}
            </p>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2 text-xs text-gray-600">
              <span>
                {s.capacity_kw ? `${s.capacity_kw.toLocaleString()} kW` : "—"}
              </span>
              <span>
                {s.guide_price ? `£${s.guide_price} ${s.price_unit || ""}` : "—"}
              </span>
            </div>
            <div className="mt-2">
              <Badge variant="confidence" level={s.confidence_level} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

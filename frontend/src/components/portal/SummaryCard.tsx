import type { ReactNode } from "react";

interface SummaryCardProps {
  label: string;
  value: number;
  sub?: string;
  icon?: ReactNode;
}

export default function SummaryCard({ label, value, sub }: SummaryCardProps) {
  return (
    <div className="bg-surface rounded-lg border border-gray-100 p-4 min-h-[88px] transition-shadow duration-150 hover:shadow-card">
      <p className="text-2xl font-bold tracking-tight text-gray-900">
        {value.toLocaleString()}
      </p>
      <p className="text-sm font-medium text-gray-600 mt-0.5">{label}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}

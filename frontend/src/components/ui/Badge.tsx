"use client";

import type { ReactNode } from "react";

export type BadgeVariant = "confidence" | "priority" | "dso" | "neutral";

const VARIANT_STYLES: Record<BadgeVariant, string> = {
  confidence:
    "bg-gray-100 text-gray-700 data-[level=high]:bg-success-100 data-[level=high]:text-success-700 data-[level=medium]:bg-warning-100 data-[level=medium]:text-warning-700 data-[level=low]:bg-danger-100 data-[level=low]:text-danger-700 data-[level=insufficient_evidence]:bg-gray-100 data-[level=insufficient_evidence]:text-gray-500 data-[level=unknown]:bg-gray-100 data-[level=unknown]:text-gray-400",
  priority:
    "data-[level=high]:bg-success-100 data-[level=high]:text-success-700 data-[level=medium]:bg-warning-100 data-[level=medium]:text-warning-700 data-[level=low]:bg-danger-100 data-[level=low]:text-danger-700 bg-gray-100 text-gray-700",
  dso: "bg-brand-50 text-brand-700",
  neutral: "bg-gray-100 text-gray-700",
};

const DSO_PALETTE: Record<string, string> = {
  NGED: "bg-blue-100 text-blue-800",
  SPEN: "bg-green-100 text-green-800",
  ENWL: "bg-purple-100 text-purple-800",
  SSEN: "bg-orange-100 text-orange-800",
  UKPN: "bg-teal-100 text-teal-800",
  NPG: "bg-indigo-100 text-indigo-800",
  NESO: "bg-gray-100 text-gray-800",
};

interface BadgeProps {
  variant?: BadgeVariant;
  level?: string;
  dso?: string;
  className?: string;
  children?: ReactNode;
}

export default function Badge({
  variant = "neutral",
  level,
  dso,
  className = "",
  children,
}: BadgeProps) {
  const base =
    "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap";

  if (variant === "dso" && dso) {
    const colour = DSO_PALETTE[dso] || DSO_PALETTE.NESO;
    return (
      <span className={`${base} ${colour} ${className}`} data-dso={dso}>
        {children ?? dso}
      </span>
    );
  }

  return (
    <span
      className={`${base} ${VARIANT_STYLES[variant]} ${className}`}
      data-level={level}
    >
      {children ?? level}
    </span>
  );
}

export { DSO_PALETTE };

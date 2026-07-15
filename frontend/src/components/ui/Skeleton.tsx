"use client";

interface SkeletonProps {
  className?: string;
  rows?: number;
  ariaLabel?: string;
}

export default function Skeleton({
  className = "",
  rows = 1,
  ariaLabel = "Loading content",
}: SkeletonProps) {
  return (
    <div
      className={`animate-pulse space-y-2 ${className}`}
      role="status"
      aria-live="polite"
      aria-label={ariaLabel}
    >
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="h-3 bg-gray-200 rounded"
          style={{ width: `${Math.max(40, 100 - i * 8)}%` }}
        />
      ))}
      <span className="sr-only">{ariaLabel}</span>
    </div>
  );
}

export function SkeletonTable({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="space-y-3" role="status" aria-label="Loading table">
      <div className="animate-pulse h-4 bg-gray-200 rounded w-1/3" />
      <div className="space-y-2">
        {Array.from({ length: rows }).map((_, r) => (
          <div key={r} className="flex gap-3">
            {Array.from({ length: cols }).map((_, c) => (
              <div
                key={c}
                className="animate-pulse h-3 bg-gray-200 rounded flex-1"
                style={{ animationDelay: `${(r * cols + c) * 60}ms` }}
              />
            ))}
          </div>
        ))}
      </div>
      <span className="sr-only">Loading table</span>
    </div>
  );
}

export function SkeletonCard({ className = "" }: { className?: string }) {
  return (
    <div
      className={`bg-surface-muted rounded-lg p-4 ${className}`}
      role="status"
      aria-label="Loading"
    >
      <div className="animate-pulse space-y-3">
        <div className="h-6 bg-gray-200 rounded w-1/3" />
        <div className="h-3 bg-gray-200 rounded w-1/2" />
        <div className="h-3 bg-gray-200 rounded w-2/3" />
      </div>
    </div>
  );
}

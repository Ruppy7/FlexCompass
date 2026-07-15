"use client";

interface LoadingSpinnerProps {
  label?: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const SIZE_CLASSES: Record<"sm" | "md" | "lg", string> = {
  sm: "w-4 h-4 border-2",
  md: "w-8 h-8 border-4",
  lg: "w-12 h-12 border-[5px]",
};

export default function LoadingSpinner({
  label = "Loading…",
  size = "md",
  className = "",
}: LoadingSpinnerProps) {
  return (
    <div
      className={`text-center py-6 ${className}`}
      role="status"
      aria-live="polite"
    >
      <div
        className={`animate-spin inline-block ${SIZE_CLASSES[size]} border-brand-600 border-t-transparent rounded-full mb-3`}
        aria-hidden="true"
      />
      {label && <p className="text-gray-600 text-sm">{label}</p>}
      <span className="sr-only">{label}</span>
    </div>
  );
}

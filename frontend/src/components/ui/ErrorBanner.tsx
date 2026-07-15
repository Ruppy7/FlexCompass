"use client";

interface ErrorBannerProps {
  title?: string;
  message: string;
  className?: string;
}

export default function ErrorBanner({
  title = "Something went wrong",
  message,
  className = "",
}: ErrorBannerProps) {
  return (
    <div
      className={`bg-danger-50 border border-danger-200 rounded-lg p-4 ${className}`}
      role="alert"
    >
      <p className="text-danger-700 font-medium">{title}</p>
      <p className="text-danger-600 text-sm mt-1">{message}</p>
    </div>
  );
}

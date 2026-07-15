import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FlexCompass — GB Grid Data Research",
  description:
    "Open-source research tools for public Great Britain electricity-network and flexibility-market data.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-surface-muted antialiased">
        {children}
      </body>
    </html>
  );
}

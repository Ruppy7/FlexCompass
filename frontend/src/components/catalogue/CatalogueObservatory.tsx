"use client";

import { KeyboardEvent, useEffect, useRef, useState } from "react";

import ErrorBanner from "@/components/ui/ErrorBanner";
import { fetchCataloguePortals, isCatalogueAbortError } from "@/lib/api";
import type { CataloguePortalSummary, CatalogueTab } from "@/lib/types";
import DatasetTable from "./DatasetTable";
import PortalCoverageGrid from "./PortalCoverageGrid";

const TABS: { key: CatalogueTab; label: string }[] = [
  { key: "coverage", label: "Coverage" },
  { key: "datasets", label: "Datasets" },
];

export default function CatalogueObservatory() {
  const [tab, setTab] = useState<CatalogueTab>("coverage");
  const [portals, setPortals] = useState<CataloguePortalSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestToken = useRef(0);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    if (tab !== "coverage") {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    const token = ++requestToken.current;
    setLoading(true);
    setError(null);
    void fetchCataloguePortals({ signal: controller.signal }).then((page) => {
      if (requestToken.current === token) setPortals(page.items);
    }).catch((caught: unknown) => {
      if (requestToken.current !== token || isCatalogueAbortError(caught)) return;
      setError(caught instanceof Error ? caught.message : "Failed to fetch catalogue portals");
    }).finally(() => {
      if (requestToken.current === token) setLoading(false);
    });
    return () => {
      controller.abort();
      requestToken.current += 1;
    };
  }, [tab]);

  const selectTab = (next: CatalogueTab, index: number) => {
    setTab(next);
    queueMicrotask(() => tabRefs.current[index]?.focus());
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const nextIndex = (index + direction + TABS.length) % TABS.length;
    selectTab(TABS[nextIndex].key, nextIndex);
  };

  return (
    <section className="space-y-5" aria-labelledby="catalogue-heading">
      <div><h2 id="catalogue-heading" className="text-xl font-semibold">Catalogue Observatory</h2><p className="mt-1 text-sm text-gray-600">Read-only public catalogue coverage and last-valid dataset evidence.</p></div>
      <div role="tablist" aria-label="Catalogue views" className="flex gap-1 border-b border-gray-200">
        {TABS.map(({ key, label }, index) => <button key={key} id={`catalogue-${key}-tab`} aria-controls={`catalogue-${key}-panel`} ref={(element) => { tabRefs.current[index] = element; }} type="button" role="tab" aria-selected={tab === key} tabIndex={tab === key ? 0 : -1} onClick={() => setTab(key)} onKeyDown={(event) => handleKeyDown(event, index)} className={`border-b-2 px-4 py-2 text-sm font-medium ${tab === key ? "border-brand-600 text-brand-700" : "border-transparent text-gray-500"}`}>{label}</button>)}
      </div>
      <div role="tabpanel" id={`catalogue-${tab}-panel`} aria-labelledby={`catalogue-${tab}-tab`}>
        {tab === "coverage" && <>{loading && <p className="text-sm text-gray-600">Loading portal coverage…</p>}{error && <ErrorBanner title="Coverage unavailable" message={error} />}{!loading && !error && <PortalCoverageGrid portals={portals} />}</>}
        {tab === "datasets" && <DatasetTable />}
      </div>
    </section>
  );
}

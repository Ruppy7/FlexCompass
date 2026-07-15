"use client";

import {
  useState,
  useEffect,
  useRef,
  useCallback,
  Suspense,
  type KeyboardEvent,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type {
  FlexZone,
  FlexSignal,
  PortalDataset,
  IngestStatus,
} from "@/lib/types";
import {
  fetchZones,
  fetchSignals,
  fetchPortalDatasets,
  fetchIngestStatus,
} from "@/lib/api";
import ErrorBanner from "@/components/ui/ErrorBanner";
import { SkeletonTable, SkeletonCard } from "@/components/ui/Skeleton";
import SummaryCard from "./portal/SummaryCard";
import ZonesTab from "./portal/ZonesTab";
import SignalsTab from "./portal/SignalsTab";
import DatasetsTab from "./portal/DatasetsTab";

const TABS = [
  { key: "zones", label: "Zones" },
  { key: "signals", label: "Signals" },
  { key: "datasets", label: "Datasets" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

const TAB_SET = new Set<string>(TABS.map((t) => t.key));

function parseTab(raw: string | null): TabKey {
  if (raw && TAB_SET.has(raw)) return raw as TabKey;
  return "zones";
}

function PortalIntelligenceInner() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [activeTab, setActiveTab] = useState<TabKey>(() =>
    parseTab(searchParams.get("tab")),
  );

  const [zones, setZones] = useState<FlexZone[]>([]);
  const [signals, setSignals] = useState<FlexSignal[]>([]);
  const [datasets, setDatasets] = useState<PortalDataset[]>([]);
  const [ingestStatus, setIngestStatus] = useState<IngestStatus | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const tabRefs = useRef<Record<TabKey, HTMLButtonElement | null>>({
    zones: null,
    signals: null,
    datasets: null,
  });

  useEffect(() => {
    Promise.all([
      fetchZones(),
      fetchSignals(),
      fetchPortalDatasets(),
      fetchIngestStatus(),
    ])
      .then(([z, s, d, ist]) => {
        setZones(z);
        setSignals(s);
        setDatasets(d);
        setIngestStatus(ist);
        setError(null);
      })
      .catch((err: Error) =>
        setError(err.message || "Failed to load portal intelligence data"),
      )
      .finally(() => setLoading(false));
  }, []);

  const selectTab = useCallback(
    (tab: TabKey) => {
      setActiveTab(tab);

      const params = new URLSearchParams(searchParams.toString());
      if (params.get("tab") === tab) return;
      params.set("tab", tab);
      router.replace(`?${params.toString()}`, { scroll: false });
    },
    [router, searchParams],
  );

  const onTabKeyDown = (e: KeyboardEvent<HTMLButtonElement>, idx: number) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft" && e.key !== "Home" && e.key !== "End") {
      return;
    }
    e.preventDefault();
    let nextIdx = idx;
    if (e.key === "ArrowRight") nextIdx = (idx + 1) % TABS.length;
    if (e.key === "ArrowLeft") nextIdx = (idx - 1 + TABS.length) % TABS.length;
    if (e.key === "Home") nextIdx = 0;
    if (e.key === "End") nextIdx = TABS.length - 1;
    const next = TABS[nextIdx];
    selectTab(next.key);
    tabRefs.current[next.key]?.focus();
  };

  if (loading) {
    return (
      <div className="bg-surface rounded-lg shadow-card p-6 animate-fade-in" aria-busy="true">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
        <SkeletonTable rows={6} cols={5} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-surface rounded-lg shadow-card p-6 animate-fade-in">
        <ErrorBanner
          title="Failed to load portal intelligence"
          message={error}
        />
      </div>
    );
  }

  const dsos = Array.from(new Set(zones.map((z) => z.dso)));

  const activePanelId = `panel-${activeTab}`;
  const activeTabId = `tab-${activeTab}`;

  return (
    <div className="bg-surface rounded-lg shadow-card animate-fade-in">
      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 p-6 border-b">
        <SummaryCard
          label="Zones"
          value={zones.length}
          sub={`${dsos.length} DSOs`}
        />
        <SummaryCard
          label="Signals"
          value={signals.length}
          sub={`${new Set(signals.map((s) => s.dso)).size} DSOs`}
        />
        <SummaryCard
          label="Datasets"
          value={datasets.length}
          sub="portal datasets"
        />
        <SummaryCard
          label="Ingested"
          value={ingestStatus?.total_records ?? 0}
          sub="records in DB"
        />
      </div>

      {/* Tablist */}
      <div
        role="tablist"
        aria-label="Portal intelligence sections"
        className="flex border-b px-6 overflow-x-auto"
      >
        {TABS.map((tab, idx) => {
          const isActive = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              ref={(el) => {
                tabRefs.current[tab.key] = el;
              }}
              id={`tab-${tab.key}`}
              role="tab"
              type="button"
              aria-selected={isActive}
              aria-controls={`panel-${tab.key}`}
              tabIndex={isActive ? 0 : -1}
              onClick={() => selectTab(tab.key)}
              onKeyDown={(e) => onTabKeyDown(e, idx)}
              className={`px-4 min-h-[44px] text-sm font-medium border-b-2 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 ${
                isActive
                  ? "border-brand-600 text-brand-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Tabpanel */}
      <div
        role="tabpanel"
        id={activePanelId}
        aria-labelledby={activeTabId}
        className="p-6"
      >
        {activeTab === "zones" && <ZonesTab zones={zones} />}
        {activeTab === "signals" && <SignalsTab signals={signals} />}
        {activeTab === "datasets" && <DatasetsTab datasets={datasets} />}
      </div>
    </div>
  );
}

export default function PortalIntelligence() {
  return (
    <Suspense
      fallback={
        <div className="bg-surface rounded-lg shadow-card p-6" aria-busy="true">
          <SkeletonTable rows={6} cols={5} />
        </div>
      }
    >
      <PortalIntelligenceInner />
    </Suspense>
  );
}

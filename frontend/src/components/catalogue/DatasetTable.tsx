"use client";

import { useEffect, useRef, useState } from "react";

import ErrorBanner from "@/components/ui/ErrorBanner";
import { fetchCatalogueDatasets, isCatalogueAbortError } from "@/lib/api";
import type {
  CatalogueAccessStatus,
  CatalogueDatasetSummary,
  CatalogueLifecycleStatus,
  CatalogueMaintenanceState,
  CataloguePortalId,
  CataloguePublicationPattern,
  Page,
} from "@/lib/types";
import CatalogueStateBadge from "./CatalogueStateBadge";
import DatasetDetail from "./DatasetDetail";

const PAGE_SIZE = 20;

export default function DatasetTable() {
  const requestToken = useRef(0);
  const [portalId, setPortalId] = useState<CataloguePortalId | "">("");
  const [query, setQuery] = useState("");
  const [lifecycle, setLifecycle] = useState<CatalogueLifecycleStatus | "">("");
  const [publication, setPublication] = useState<CataloguePublicationPattern | "">("");
  const [access, setAccess] = useState<CatalogueAccessStatus | "">("");
  const [maintenance, setMaintenance] = useState<CatalogueMaintenanceState | "">("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<CatalogueDatasetSummary> | null>(null);
  const [selected, setSelected] = useState<CatalogueDatasetSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const token = ++requestToken.current;
    setLoading(true);
    setError(null);
    setSelected(null);
    void fetchCatalogueDatasets(
      {
        portalId: portalId || undefined,
        query: query || undefined,
        lifecycle: lifecycle || undefined,
        publication: publication || undefined,
        access: access || undefined,
        maintenance: maintenance || undefined,
        limit: PAGE_SIZE,
        offset,
      },
      { signal: controller.signal },
    ).then((result) => {
      if (requestToken.current === token) setPage(result);
    }).catch((caught: unknown) => {
      if (requestToken.current !== token || isCatalogueAbortError(caught)) return;
      setPage(null);
      setError(caught instanceof Error ? caught.message : "Failed to fetch catalogue datasets");
    }).finally(() => {
      if (requestToken.current === token) setLoading(false);
    });
    return () => {
      controller.abort();
      requestToken.current += 1;
    };
  }, [access, lifecycle, maintenance, offset, portalId, publication, query]);

  const resetPage = () => {
    setOffset(0);
    setSelected(null);
  };

  return (
    <section aria-label="Catalogue datasets" className="space-y-4">
      <div className="grid gap-3 rounded-lg border border-gray-200 bg-white p-4 sm:grid-cols-2 lg:grid-cols-6">
        <label className="text-sm font-medium">Portal<select aria-label="Portal" value={portalId} onChange={(event) => { setPortalId(event.target.value as CataloguePortalId | ""); resetPage(); }} className="mt-1 block w-full rounded border p-2"><option value="">All portals</option>{["nged", "spen", "enwl", "ssen", "ukpn", "npg", "neso"].map((id) => <option key={id} value={id}>{id.toUpperCase()}</option>)}</select></label>
        <label className="text-sm font-medium">Search datasets<input aria-label="Search datasets" value={query} onChange={(event) => { setQuery(event.target.value); resetPage(); }} className="mt-1 block w-full rounded border p-2" /></label>
        <label className="text-sm font-medium">Lifecycle<select aria-label="Lifecycle" value={lifecycle} onChange={(event) => { setLifecycle(event.target.value as CatalogueLifecycleStatus | ""); resetPage(); }} className="mt-1 block w-full rounded border p-2"><option value="">All</option>{["active", "historical_archive", "superseded", "retired", "unknown"].map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}</select></label>
        <label className="text-sm font-medium">Publication<select aria-label="Publication" value={publication} onChange={(event) => { setPublication(event.target.value as CataloguePublicationPattern | ""); resetPage(); }} className="mt-1 block w-full rounded border p-2"><option value="">All</option>{["continuous", "periodic", "event_driven", "static_reference", "closed_period", "unknown"].map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}</select></label>
        <label className="text-sm font-medium">Access<select aria-label="Access" value={access} onChange={(event) => { setAccess(event.target.value as CatalogueAccessStatus | ""); resetPage(); }} className="mt-1 block w-full rounded border p-2"><option value="">All</option>{["public", "registered", "restricted", "unreachable", "unknown"].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
        <label className="text-sm font-medium">Maintenance<select aria-label="Maintenance" value={maintenance} onChange={(event) => { setMaintenance(event.target.value as CatalogueMaintenanceState | ""); resetPage(); }} className="mt-1 block w-full rounded border p-2"><option value="">All</option>{["on_schedule", "possibly_overdue", "stale", "expected_dormant", "unknown"].map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}</select></label>
      </div>

      {loading && <p className="text-sm text-gray-600">Loading datasets…</p>}
      {error && <ErrorBanner title="Datasets unavailable" message={error} />}
      {!loading && !error && page?.items.length === 0 && <p className="rounded-lg border bg-white p-6 text-center text-sm text-gray-600">No datasets match these filters.</p>}
      {!loading && !error && page && page.items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
          <table className="min-w-full text-left text-sm"><thead><tr className="border-b"><th className="p-3">Dataset</th><th>Portal</th><th>Lifecycle</th><th>Publication</th><th>Access</th><th><span className="sr-only">Action</span></th></tr></thead><tbody>{page.items.map((dataset) => <tr key={dataset.dataset_ref} className="border-b"><td className="p-3"><span className="font-medium">{dataset.title ?? "Unknown"}</span><br /><span className="font-mono text-xs text-gray-500">{dataset.source_dataset_id}</span></td><td>{dataset.portal_id.toUpperCase()}</td><td><CatalogueStateBadge state={dataset.lifecycle_status} /></td><td><CatalogueStateBadge state={dataset.publication_pattern} /></td><td><CatalogueStateBadge state={dataset.access_status} /></td><td className="p-3"><button type="button" onClick={() => setSelected(dataset)} className="text-brand-700 underline">View {dataset.title ?? "Unknown"}</button></td></tr>)}</tbody></table>
        </div>
      )}

      {page && !error && (
        <div className="flex items-center justify-between text-sm">
          <span>{page.total} datasets · offset {page.offset}</span>
          <div className="flex gap-2"><button type="button" aria-label="Previous page" disabled={page.offset === 0} onClick={() => { setSelected(null); setOffset(Math.max(0, page.offset - page.limit)); }} className="rounded border px-3 py-1 disabled:opacity-50">Previous</button><button type="button" aria-label="Next page" disabled={page.offset + page.limit >= page.total} onClick={() => { setSelected(null); setOffset(page.offset + page.limit); }} className="rounded border px-3 py-1 disabled:opacity-50">Next</button></div>
        </div>
      )}
      {selected && <DatasetDetail datasetRef={selected.dataset_ref} portalId={selected.portal_id} />}
    </section>
  );
}

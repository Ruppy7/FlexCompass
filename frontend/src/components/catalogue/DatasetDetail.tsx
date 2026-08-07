"use client";

import { useEffect, useRef, useState } from "react";

import ErrorBanner from "@/components/ui/ErrorBanner";
import {
  fetchCatalogueDataset,
  fetchCatalogueDatasetAssessments,
  fetchCatalogueDatasetEvidence,
  fetchCatalogueDatasetResources,
  fetchCatalogueObservations,
  isCatalogueAbortError,
} from "@/lib/api";
import type {
  CatalogueAssessment,
  CatalogueDatasetDetail,
  CatalogueEvidence,
  CatalogueObservation,
  CataloguePortalId,
  CatalogueResource,
  Page,
} from "@/lib/types";
import CatalogueStateBadge from "./CatalogueStateBadge";
import ObservationHistory from "./ObservationHistory";

interface DatasetDetailProps {
  datasetRef: string;
  portalId: CataloguePortalId;
}

interface DetailState {
  dataset: CatalogueDatasetDetail;
  resources: Page<CatalogueResource>;
  evidence: Page<CatalogueEvidence>;
  assessments: Page<CatalogueAssessment>;
  observations: Page<CatalogueObservation>;
}

const DETAIL_PAGE_LIMIT = 200;

function known(value: string | number | null | undefined): string | number {
  return value ?? "Unknown";
}

export default function DatasetDetail({ datasetRef, portalId }: DatasetDetailProps) {
  const requestToken = useRef(0);
  const [data, setData] = useState<DetailState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const token = ++requestToken.current;
    setData(null);
    setError(null);
    setLoading(true);

    void Promise.all([
      fetchCatalogueDataset(datasetRef, { signal: controller.signal }),
      fetchCatalogueDatasetResources(datasetRef, {
        signal: controller.signal,
        limit: DETAIL_PAGE_LIMIT,
        offset: 0,
      }),
      fetchCatalogueDatasetEvidence(datasetRef, {
        signal: controller.signal,
        limit: DETAIL_PAGE_LIMIT,
        offset: 0,
      }),
      fetchCatalogueDatasetAssessments(datasetRef, {
        signal: controller.signal,
        limit: DETAIL_PAGE_LIMIT,
        offset: 0,
      }),
      fetchCatalogueObservations(
        { portalId, limit: DETAIL_PAGE_LIMIT, offset: 0 },
        { signal: controller.signal },
      ),
    ]).then(([dataset, resources, evidence, assessments, observations]) => {
      if (requestToken.current !== token) return;
      setData({
        dataset,
        resources,
        evidence,
        assessments,
        observations,
      });
    }).catch((caught: unknown) => {
      if (requestToken.current !== token || isCatalogueAbortError(caught)) return;
      setError(caught instanceof Error ? caught.message : "Failed to fetch catalogue dataset");
    }).finally(() => {
      if (requestToken.current === token) setLoading(false);
    });

    return () => {
      controller.abort();
      requestToken.current += 1;
    };
  }, [datasetRef, portalId]);

  if (loading) return <p className="text-sm text-gray-600">Loading dataset detail…</p>;
  if (error) return <ErrorBanner title="Dataset detail unavailable" message={error} />;
  if (!data) return null;

  const { dataset, resources, evidence, assessments, observations } = data;
  return (
    <section aria-label="Dataset detail" className="mt-6 space-y-5 rounded-lg border border-gray-200 bg-white p-5">
      <div>
        <h3 className="text-lg font-semibold text-gray-900">{known(dataset.title)}</h3>
        <p className="mt-1 text-sm text-gray-600">{known(dataset.description)}</p>
        <p className="mt-1 font-mono text-xs text-gray-500">{dataset.dataset_ref}</p>
      </div>
      <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
        <div><dt className="font-medium">Publisher</dt><dd>{known(dataset.publisher)}</dd></div>
        <div><dt className="font-medium">Licence</dt><dd>{known(dataset.licence_title ?? dataset.licence)}</dd></div>
        <div><dt className="font-medium">Attribution</dt><dd>{known(dataset.attribution)}</dd></div>
        <div><dt className="font-medium">Observed</dt><dd>{dataset.observed_at}</dd></div>
        <div><dt className="font-medium">Lifecycle</dt><dd><CatalogueStateBadge state={dataset.lifecycle_status} /></dd></div>
        <div><dt className="font-medium">Access</dt><dd><CatalogueStateBadge state={dataset.access_status} /></dd></div>
        <div><dt className="font-medium">Publication</dt><dd><CatalogueStateBadge state={dataset.publication_pattern} /></dd></div>
        <div><dt className="font-medium">Update frequency</dt><dd>{known(dataset.declared_update_frequency_text ?? dataset.declared_update_frequency)}</dd></div>
        <div><dt className="font-medium">Themes</dt><dd>{dataset.themes.length ? dataset.themes.join(", ") : "Unknown"}</dd></div>
      </dl>

      <div><h4 className="font-semibold">Resources</h4>{resources.items.length ? <ul className="mt-2 space-y-1 text-sm">{resources.items.map((resource) => <li key={resource.id}>{known(resource.name)} · {known(resource.format)}</li>)}</ul> : <p className="text-sm text-gray-600">No resources are available.</p>}{resources.total > resources.items.length ? <p className="mt-2 text-sm text-gray-600">Showing first {resources.items.length} of {resources.total} resources.</p> : null}</div>
      <div><h4 className="font-semibold">Evidence</h4>{evidence.items.length ? <ul className="mt-2 space-y-1 text-sm">{evidence.items.map((item) => <li key={item.id}><strong>{item.classification}:</strong> {item.evidence} <CatalogueStateBadge state={item.confidence} /></li>)}</ul> : <p className="text-sm text-gray-600">No evidence is available.</p>}{evidence.total > evidence.items.length ? <p className="mt-2 text-sm text-gray-600">Showing first {evidence.items.length} of {evidence.total} evidence items.</p> : null}</div>
      <div><h4 className="font-semibold">Assessments</h4>{assessments.items.length ? <ul className="mt-2 space-y-1 text-sm">{assessments.items.map((assessment) => <li key={assessment.assessment_id}><span className="font-mono text-xs">{assessment.assessment_id}</span>: {assessment.assessment_type} · {assessment.assessment_value} · {assessment.confidence}</li>)}</ul> : <p className="text-sm text-gray-600">No assessments are available.</p>}{assessments.total > assessments.items.length ? <p className="mt-2 text-sm text-gray-600">Showing first {assessments.items.length} of {assessments.total} assessments.</p> : null}</div>
      <div><h4 className="mb-2 font-semibold">Portal observation history</h4><ObservationHistory observations={observations.items} />{observations.total > observations.items.length ? <p className="mt-2 text-sm text-gray-600">Showing first {observations.items.length} of {observations.total} observations.</p> : null}</div>
    </section>
  );
}

# Data model

FlexCompass uses a zone-authoritative model: a postcode or coordinate is a lookup
key into a network zone, and a signal refers to that zone when the public source
provides enough evidence.

The active public-data workflows are the anonymous, read-only seven-portal
catalogue CLI and the reviewed SSEN historical-HV sync and read-only query API.
`CATALOGUE_PORTALS` in `backend/app/catalogue_models.py` remains the sole portal
registry. The Next.js application exposes neither registry nor SSEN records; it
presents research status and a separate, explicitly synthetic demonstration.

## Core records

- `PortalDataset` records public catalogue metadata, API location, known fields,
  licence status, and limitations.
- `FlexZone` records a DSO area, optional postcode evidence or GeoJSON geometry,
  `source_dataset_id`, and the source `raw_record`.
- `FlexSignal` records a published flexibility requirement or observation with
  location, service, timing, capacity, price, confidence, missing fields,
  `source_dataset_id`, and `raw_record`.
- `DataSource` records the portal owner, access method, represented period,
  licence notes, quality notes, and limitations.
- `Portfolio` and `AssetGroup` are synthetic research inputs unless a user
  supplies their own data locally.
- `FitAssessment` contains transparent directional checks and missing evidence;
  it is not an eligibility or bidding decision.

## Provenance rule

Every zone or signal derived from a portal response must retain both the public
dataset identifier and the original source record. A normaliser must not invent
missing prices, dates, capacities, eligibility, or geographic precision.

## SSEN historical-outage evidence

The accepted SSEN NaFIRS HV collector reads the reviewed tracked manifest at
`data/sources/ssen-nafirs-hv.json`. Each resource produces a resource-specific
immutable snapshot whose identity includes the resource ID and source-byte
SHA-256. Canonical records are immutable event versions scoped to that
snapshot. A completed two-resource sync replaces the atomic current set in one
transaction; a failed or incomplete sync leaves it unchanged. Queries may use
that current set or an explicit snapshot set to replay earlier evidence.

The raw CSV is authoritative. Parsing retains each source row, records rejects
with safe reason codes, and attaches quality flags where a usable record needs
qualification. Incident timestamps are parsed day-first, but the publisher
timezone is unknown; canonical values therefore do not claim a UTC instant.
The publisher cadence is unknown. SEPD and SHEPD have different schemas, so
each resource has a separately validated header contract rather than a merged
inferred schema.

Only the stable origin URL from the reviewed manifest is persisted. A temporary
signed download URL returned by the approved redirect is neither provenance
nor stored data. Local materialisations remain ignored at
`data/cache/outages/registry.sqlite3` and `data/snapshots/outages/`.

## Confidence

Confidence reflects evidence completeness and geographic match quality. Polygon
or exact-postcode evidence can support higher confidence than a postcode-prefix
match. Missing core fields reduce confidence. These bands are heuristic, not a
measure of forecast accuracy.

## Storage

SQLite is used without an ORM. Structured lists and raw records are serialized
as JSON text. Generated snapshots, SQLite databases, caches, queues, and reports are ignored/local outputs and are never committed.

## Catalogue observation model

The catalogue layer adds observation-based records for public portal metadata:

- `CatalogueDataset`: one public dataset with `source_dataset_id`, `raw_record`,
  `observed_at`, declared update-frequency text, canonical public metadata,
  classification evidence, and unknown-by-default source status fields.
  Resources are nested.
- `DatasetResource`: one downloadable resource with `source_dataset_id`,
  `raw_record`, `observed_at`, URL, format, and size.
- `CatalogueObservation`: one portal-fetch observation with status, source
  content hash, dataset/resource totals, pagination completeness, warnings,
  and nullable request/response/retry facts.
- `ClassificationEvidence`: one piece of evidence supporting a non-factual
  classification (lifecycle, pattern, access, maintenance) with confidence.

### Observation identity

Each sync run produces a deterministic observation key derived from portal ID,
observation timestamp, and content hash. The content hash is SHA-256 of the
redacted source snapshot core (with FlexCompass-generated clocks stripped).
Known set-like source collections are normalised only in the hash projection;
their original order remains intact in `raw_record` and raw-page provenance.
Classifier assessments are persisted separately and do not affect immutable
source snapshot identity.

### Atomic local artifacts

Sync writes are atomic: a temporary file is written then renamed. If the
snapshot already exists with identical content, no write occurs. Failed portals
do not alter the current registry. Partial observations update conservatively
without erasing missing source facts or removing unseen children. Complete
observations are authoritative for datasets they contain: removed nullable/list
facts become unknown and obsolete current resources/evidence are reconciled.

### Secret redaction

All persisted and printed artifacts pass through `redact()`, which recursively:
- Replaces values of keys matching sensitive patterns (`authorization`,
  `token`, `api_key`, `secret`, `password`, `credential`, `cookie`) with
  `[REDACTED]`
- Replaces inline `key=value` credential patterns with `key=[REDACTED]`
- Replaces private-host and credential-bearing URLs with `[REDACTED_URL]`
- Removes signed-URL credentials, signatures, and security-token parameters
  while retaining benign query parameters and fragments needed by public URLs

### Review queue

The review queue tracks datasets with unknown classifications. Each item has a
deterministic hash ID based on portal, dataset, dimension, and reason. The
queue is replaceable (not immutable). A fresh complete or partial
classification pass replaces that portal's items; failed and unrequested portal
items are preserved.

### Dated observations

Catalogue counts, titles, and metadata are point-in-time observations, not
stable facts. The `observed_at` timestamp records when FlexCompass fetched data.
Refresh cadence and stale classification are evidence-backed and preserve
unknowns rather than inferred from absent evidence.

A non-unknown periodic maintenance result requires explicit evidence that the
dataset lifecycle is active and a defensible freshness clock. Resource
`last_modified` can supply that clock when its exact source field is retained;
generic resource `metadata_modified` is catalogue-edit metadata and is not used
as a data/release clock. Maintenance rationale records the selected clock and
its field-level provenance. Adapters do not invent lifecycle or access evidence.

## Testing boundaries

Live portal tests are opt-in via `FLEXCOMPASS_LIVE_PORTAL_TESTS=1`; seven
parametrized cases are skipped by default with zero network calls. When enabled,
each case requires a complete snapshot whose unique usable dataset count matches
the portal's reported count. Licence and attribution must be verified before
redistributing source data.

## Retired legacy surfaces

The legacy generic portal ingestors and browser-triggered mutation routes were
retired because they lacked accepted source contracts and end-to-end
provenance. The active API therefore has no route that starts catalogue or
analytical ingestion, drift processing, or database population.

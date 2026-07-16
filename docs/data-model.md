# Data model

FlexCompass uses a zone-authoritative model: a postcode or coordinate is a lookup
key into a network zone, and a signal refers to that zone when the public source
provides enough evidence.

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

## Confidence

Confidence reflects evidence completeness and geographic match quality. Polygon
or exact-postcode evidence can support higher confidence than a postcode-prefix
match. Missing core fields reduce confidence. These bands are heuristic, not a
measure of forecast accuracy.

## Storage

SQLite is used without an ORM. Structured lists and raw records are serialized
as JSON text. Local databases are generated artifacts and are never committed.

## Catalogue observation model

The catalogue layer adds observation-based records for public portal metadata:

- `CatalogueDataset`: one public dataset with `source_dataset_id`, `raw_record`,
  `observed_at`, classification evidence, lifecycle, publication pattern, and
  access status. Resources are nested.
- `DatasetResource`: one downloadable resource with `source_dataset_id`,
  `raw_record`, `observed_at`, URL, format, and size.
- `ClassificationEvidence`: one piece of evidence supporting a non-factual
  classification (lifecycle, pattern, access, maintenance) with confidence.

### Observation identity

Each sync run produces a deterministic observation key derived from portal ID,
observation timestamp, and content hash. The content hash is SHA-256 of the
redacted snapshot core (with FlexCompass-generated clocks stripped).

### Atomic local artifacts

Sync writes are atomic: a temporary file is written then renamed. If the
snapshot already exists with identical content, no write occurs. Failed syncs
do not publish partial artifacts; the previous valid state is preserved.

### Secret redaction

All persisted and printed artifacts pass through `redact()`, which recursively:
- Replaces values of keys matching sensitive patterns (`authorization`,
  `token`, `api_key`, `secret`, `password`, `credential`, `cookie`) with
  `[REDACTED]`
- Replaces inline `key=value` credential patterns with `key=[REDACTED]`
- Replaces private-host and credential-bearing URLs with `[REDACTED_URL]`

### Review queue

The review queue tracks datasets with unknown classifications. Each item has a
deterministic hash ID based on portal, dataset, dimension, and reason. The
queue is replaceable (not immutable) and preserves items for failed portals.

### Dated observations

Catalogue counts, titles, and metadata are point-in-time observations, not
stable facts. The `observed_at` timestamp records when FlexCompass fetched data.

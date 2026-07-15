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

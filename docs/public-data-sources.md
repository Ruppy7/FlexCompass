# Public data source register

This register identifies public portals supported or planned by FlexCompass. A
portal being public does not mean every resource has the same licence or access
conditions. Dataset-level terms must be checked before redistribution. Portal
and catalogue access was last checked on 15 July 2026.

| Owner | Official portal | Public catalogue API | Catalogue authentication | Licence status | Current limitation |
|---|---|---|---|---|---|
| National Grid Electricity Distribution | https://connecteddata.nationalgrid.co.uk | `https://connecteddata.nationalgrid.co.uk/api/3/action` (CKAN) | None observed | Verify per dataset; many catalogue entries do not declare a licence | Dataset identifiers, resource licences, and schemas need contract tests |
| SP Energy Networks | https://spenergynetworks.opendatasoft.com | `https://spenergynetworks.opendatasoft.com/api/explore/v2.1` | None observed | Verify per dataset; some catalogue entries do not declare a licence | Record visibility, resource coverage, and update schedules vary |
| Electricity North West | https://electricitynorthwest.opendatasoft.com | `https://electricitynorthwest.opendatasoft.com/api/explore/v2.1` | None observed | Verify per dataset | Record visibility and download conditions vary by resource |
| Scottish and Southern Electricity Networks | https://data.ssen.co.uk | `https://data-api.ssen.co.uk/api/3/action` (CKAN) | None observed | Verify per dataset | Resource formats, history, and schemas vary |
| UK Power Networks | https://ukpowernetworks.opendatasoft.com | `https://ukpowernetworks.opendatasoft.com/api/explore/v2.1` | None observed | Verify per dataset | Some datasets publish metadata or attachments without public record queries |
| Northern Powergrid | https://northernpowergrid.opendatasoft.com | `https://northernpowergrid.opendatasoft.com/api/explore/v2.1` | None observed | Verify per dataset | Some network asset datasets have separate access-request conditions |
| National Energy System Operator | https://www.neso.energy/data-portal | `https://api.neso.energy/api/3/action` (CKAN) | None observed; an account is optional for subscriptions and favourites | Verify per dataset; the current catalogue names the NESO Open Data Licence | National and transmission-system data is context, not a substitute for DSO outage or local-flexibility evidence |

## Accepted SSEN NaFIRS HV source

The reviewed analytical source is SSEN Distribution dataset `nafirs-hv-faults`, package `b0a58349-2ce6-4fa8-9238-a5564f966433`:

- SEPD maps to resource `ab32515f-76f2-421d-8034-7d5b01325a33`.
- SHEPD maps to resource `673578c9-f531-41a5-a17c-0b35bc0fae4c`.

The tracked source contract is `data/sources/ssen-nafirs-hv.json`, with reviewed
licence evidence at `data/sources/evidence/ssen-nafirs-hv-licence.json`.
Attribution is **SSEN Distribution**. The dataset is licensed under
[Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/);
the reviewed evidence says source bytes may be redistributed with SSEN Distribution attribution.
The repository's MIT licence does not replace those terms.

The raw CSV downloads are authoritative for parsing. The public CKAN DataStore
was observed to contain a day/month defect, so it is not used as event-time
authority. Raw incident timestamps are interpreted day-first. The publisher
timezone is unknown and publisher cadence is unknown. SEPD and SHEPD have
different schemas; both exact headers are validated independently.

The collector performs anonymous read-only GET requests to each stable origin
URL and accepts only the contract's narrowly approved download redirect. It
does not persist the temporary signed download URL. The collector creates
resource-specific immutable snapshots and immutable event versions. Only a successful two-resource
transaction advances the atomic current set; an explicit snapshot set supports
reproducible replay.

Run from the repository root so the CLI defaults resolve to the documented,
Git-ignored root `data/` paths:

```powershell
$env:PYTHONPATH = "backend"
python -m app.outage_cli sync ssen-nafirs-hv
python -m uvicorn app.main:app --reload --port 8099
```

Local outputs are ignored: the SQLite database is
`data/cache/outages/registry.sqlite3`, and source snapshots are under
`data/snapshots/outages/`. Parser rejects are retained with safe reason codes;
accepted events can carry quality flags. The read-only API paths are:

- `/api/v1/outages/events`
- `/api/v1/outages/events/{event_id}`
- `/api/v1/outages/summary`
- `/api/v1/outages/snapshots`

With the API running, use a second repository-root PowerShell terminal:

```powershell
$apiBase = "http://127.0.0.1:8099/api/v1/outages"
$snapshots = Invoke-RestMethod -Uri "$apiBase/snapshots"
$list = Invoke-RestMethod -Uri "$apiBase/events?limit=1"
$event = $list.items | Select-Object -First 1
$eventId = [uri]::EscapeDataString($event.event_id)
$detailSnapshotId = [uri]::EscapeDataString($event.source_snapshot_id)
$detail = Invoke-RestMethod -Uri "$apiBase/events/$eventId`?source_snapshot_id=$detailSnapshotId"
$replayQuery = ($list.evidence_scope.snapshot_ids | ForEach-Object { "source_snapshot_id=$([uri]::EscapeDataString($_))" }) -join "&"
$replayList = Invoke-RestMethod -Uri "$apiBase/events`?$replayQuery"
$replaySummary = Invoke-RestMethod -Uri "$apiBase/summary`?$replayQuery"
```

Detail identity requires exactly one `source_snapshot_id`: use the returned
event's `event_id` and its own `source_snapshot_id`, URI-escaped as above. Zero
or two detail selectors return `422`. List and summary explicit replay uses the
repeatable singular `source_snapshot_id` wire name supplied as an exact
two-resource snapshot set. That set is distinct from detail's one-snapshot
event-version identity.

These records are historical aggregate incidents, not household histories,
real-time status, or a forecast. This non-household network evidence does not establish causality
between flexibility and outage outcomes, and does not show outage prevention.
It must not be used to infer individual customer histories, private data,
bidding eligibility, dispatch actions, or commercial performance.

Anonymous catalogue access does not prove that every dataset resource is
anonymous or redistributable. `CATALOGUE_PORTALS` in
`backend/app/catalogue_models.py` is the sole active portal registry: an
immutable mapping and fixed tuple of exactly seven canonical IDs. Its public
portal locations are the source of truth for the CLI and observatory. Generated
snapshots, SQLite databases, caches, queues, and reports are ignored/local
outputs and must not be committed.

## Catalogue intelligence workflow

The active public-data workflow uses the anonymous, read-only seven-portal
catalogue CLI to create local observations and the GET-only API/UI to inspect
safe projections. The UI never starts a sync. Run commands from the repository
root using the project venv.

### Sync

Fetch public metadata with anonymous read-only GET requests:

```powershell
$env:PYTHONPATH = "backend"
python -m app.catalogue_cli sync --portal all
python -m app.catalogue_cli sync --portal nged
```

Outputs (all git-ignored): SQLite registry at
`data/cache/catalogue/registry.sqlite3`, JSON snapshots at
`data/snapshots/catalogues/<timestamp>/<portal>.json`, and review queue at
`data/cache/catalogue/review-queue.json`. The registry and snapshot root may be
overridden with `FLEXCOMPASS_CATALOGUE_DB_PATH` and
`FLEXCOMPASS_CATALOGUE_SNAPSHOT_DIR`; these are local path settings and must not
contain secrets. Snapshots are atomic and immutable.

Every requested portal receives a durable current-attempt record. A failed
attempt creates no observation and does not replace last-valid evidence. A
partial observation and snapshot are retained, but they do not become the API's
last-valid dataset source. Complete observations reconcile mutable registry
facts; API dataset reads still come only from complete immutable snapshots that
pass path, schema, identity, association, count, and content-hash validation.

### Diff

Compare two local snapshots:

```powershell
python -m app.catalogue_cli diff --before data/snapshots/catalogues/20260715T120000.000000Z/nged.json --after data/snapshots/catalogues/20260716T120000.000000Z/nged.json
```

Changes: `dataset_added`, `dataset_removed`, `metadata_changed`,
`source_evidence_changed`, `resources_replaced`, `access_changed`. Snapshot
schema, manifest semantics, unique usable counts, and content hashes are
validated before comparison. A partial snapshot never produces a definitive
dataset-removal claim.

### Review queue

Print unresolved evidence items:

```powershell
python -m app.catalogue_cli review-queue --format json
```

### Read-only catalogue API

After local sync, the public catalogue contract contains exactly these eight
versioned GET-only routes:

- `/api/v1/catalogue/portals`
- `/api/v1/catalogue/portals/{portal_id}`
- `/api/v1/catalogue/datasets`
- `/api/v1/catalogue/datasets/{dataset_ref}`
- `/api/v1/catalogue/datasets/{dataset_ref}/resources`
- `/api/v1/catalogue/datasets/{dataset_ref}/evidence`
- `/api/v1/catalogue/datasets/{dataset_ref}/assessments`
- `/api/v1/catalogue/observations`

Collection limits default to 50 and are bounded from 1 to 200; offsets are
non-negative. Dataset filters cover portal, text, lifecycle, publication
pattern, access status, and maintenance state. Observation history filters cover
portal and `complete`, `partial`, or `failed` status, although a failed refresh
attempt has no observation row and appears through portal coverage state
instead. Dataset references are opaque portal-scoped identifiers: use the value
returned by the API unchanged and URI-encode it as one path segment.

Portal state distinguishes the newest attempt, newest complete observation,
newest complete snapshot validation, and last-valid complete snapshot. An
invalid newest complete snapshot may degrade to an older valid one. When no
valid complete snapshot exists, `snapshot_available` is false and no mutable
row, legacy seed, or partial snapshot is substituted. The 168-hour due window
and `current`, `overdue`, or `never_attempted` review status are FlexCompass
operational policy, not publisher cadence or a live-freshness guarantee.

The hidden retired `/api/portal/datasets` surface returns `410 Gone` for `GET`,
`HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`, and `OPTIONS`, is absent from OpenAPI,
and never reads legacy rows.

### Catalogue web workflow

The web application opens on `Research Overview`. `Catalogue Observatory`
contains `Coverage` and `Datasets`: coverage always names all seven configured
portals and shows attempt, review, validation, last-valid, degraded, and
availability states; datasets use server filters and pagination, safe detail,
and portal observation history. `Synthetic Demo` remains a separate workflow
and uses no current portal data. Unknown and failure states are visible as text,
not colour alone.

## Classification dimensions

Each dataset is independently classified along four axes with evidence and
confidence (`high`, `medium`, `low`, `unknown`). Unknown values are preserved.

- **Lifecycle**: `active`, `historical_archive`, `superseded`, `retired`,
  `unknown`.
- **Publication pattern**: `continuous`, `periodic`, `event_driven`,
  `static_reference`, `closed_period`, `unknown`.
- **Access status**: `public`, `registered`, `restricted`, `unreachable`,
  `unknown`.
- **Maintenance state**: `on_schedule`, `possibly_overdue`, `stale`,
  `expected_dormant`, `unknown`. Stale = active + periodic + cadence observed +
  defensible latest data age exceeds cadence x grace multiplier. A non-unknown
  periodic maintenance result requires explicit active-lifecycle evidence plus
  a freshness clock with field-level provenance. A resource `last_modified`
  value can be such a clock; generic resource `metadata_modified` cannot.
  Static, archive, and event-driven datasets with compatible lifecycle evidence
  are `expected_dormant`. Adapters preserve unknown lifecycle/access when no
  explicit verified evidence is available.

## Provenance and secret redaction

Catalogue dataset, resource, and classification-evidence records retain
`source_dataset_id`, `raw_record`, and `observed_at`. A catalogue observation
separately records its observation ID and time, portal ID, status, content hash,
counts, completeness, warnings, and nullable request/response/retry facts.
Content hashes (SHA-256 of the redacted source snapshot, separate from
classifier assessments) support deduplication. Benign public URL query
parameters are retained. All
artifacts are redacted of: authentication keys (`authorization`, `token`,
`api_key`, `secret`, `password`, `credential`, `cookie`), inline credential
patterns, Basic/Bearer values, private-host URLs, credential-bearing URLs, and
common signed-URL credentials/signatures/security tokens. Benign URL fragments
are retained; credential-bearing fragment pairs are removed selectively.

These canonical records and raw provenance are internal evidence. The API may
project safe declared licence and attribution metadata, but does not expose
`raw_record`, raw pages, request URLs, local snapshot/database paths,
authentication setting names, raw or internal-safe errors, or reviewer identity.
Public URLs are projected without query or fragment material. Declared licence
metadata is not verification and does not relicense source data.

## Limitations

Catalogue metadata is not analytical ingestion, eligibility assessment,
bidding/dispatch/asset-control advice, forecasting, or commercial advice.
Counts and metadata are dated observations, not stable facts. Licence and
attribution must be verified before redistributing source data.

The web application exposes safe catalogue metadata, not verified analytical
portal records. Catalogue metadata is discovery/evidence only: it is not
analytical ingestion, proof of live freshness or analytical readiness,
eligibility assessment, bidding, dispatch, asset control, forecasting, or
commercial advice. Legacy generic portal ingestors and browser-triggered
mutation routes are retired; no active public route starts ingestion, sync, or
drift processing.

Live portal tests are opt-in via `FLEXCOMPASS_LIVE_PORTAL_TESTS=1`; seven
parametrized cases are skipped by default with zero network calls. Enabled cases
require complete observations and an exact match between expected count and
unique usable dataset IDs.

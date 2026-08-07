# FlexCompass

FlexCompass is an independent open-source research toolkit for exploring public
data about Great Britain's electricity networks and local flexibility markets.
It bridges energy-domain research with reproducible Python data pipelines, a
FastAPI research API, and a small Next.js interface.

The active public-data workflows are the anonymous, read-only seven-portal
catalogue CLI and observatory, plus the reviewed SSEN historical-HV outage sync
and query path.

The local API exposes verified SSEN outage evidence after a user runs the local
outage sync. It also exposes safe projections of locally observed catalogue
metadata. The Next.js application keeps the research-status overview as its
default, adds a read-only catalogue observatory, and retains the explicitly
synthetic demonstration as a separate workflow. The web application does not
start catalogue or outage syncs and does not expose SSEN outage records.

The legacy generic portal ingestors and browser-triggered mutation routes were
retired because they lacked accepted source contracts and end-to-end
provenance.

The repository also contains SQLite storage, provenance-preserving models,
postcode and geometry matching, data-quality utilities, synthetic portfolio
examples, and directional report generation.

The first accepted analytical source is the public SSEN Distribution NaFIRS HV
historical-outage dataset. From the repository root, sync its two reviewed CSV
resources so the default output paths remain under the root `data/` directory:

```powershell
$env:PYTHONPATH = "backend"
python -m app.outage_cli sync ssen-nafirs-hv
python -m uvicorn app.main:app --reload --port 8099
```

This writes the Git-ignored local database
`data/cache/outages/registry.sqlite3` and immutable source artifacts under
`data/snapshots/outages/`. Start the API as shown below, then query the four
read-only paths `/api/v1/outages/events`,
`/api/v1/outages/events/{event_id}`, `/api/v1/outages/summary`, and
`/api/v1/outages/snapshots`. Event filters use the atomic current set unless an
explicit snapshot set is supplied for replay. With the API running, use a
second repository-root PowerShell terminal for this copyable query workflow:

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
or two detail selectors return `422`. List and summary replay instead use the
repeatable singular `source_snapshot_id` wire name supplied as an exact
two-resource snapshot set; this is distinct from the detail route's one-snapshot
event-version identity.

This is a research project, not a product. It does not bid, dispatch or control
assets, establish eligibility, forecast revenue, or provide commercial advice.
Any scores are heuristic and directional.

The SSEN records are aggregate incidents, not household histories or a
real-time operational feed. They are non-household network evidence, do not
establish causality between flexibility and outages, and do not demonstrate
outage prevention.

## Data status

No checked-in canonical zone, signal, or market-rule dataset is published.
FlexCompass does not publish hand-curated claims as if they were current market
facts. Normalised records should be created from public portal responses only
after their schemas, provenance, licence, and limitations are verified.

Downloaded records, catalogue snapshots and queues, generated SQLite databases,
caches, and reports stay local and are ignored by Git. See
[public data sources](docs/public-data-sources.md) for the source register and
verification status.

## Quick start

Python 3.11+ and Node.js 20.9+ on the 20.x line, or Node.js 22+, are expected.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
Copy-Item .env.example .env
python -m uvicorn backend.app.main:app --reload --port 8099
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. The frontend proxies `/api` to the backend on port
8099.

## Public catalogue metadata

`CATALOGUE_PORTALS` in `backend/app/catalogue_models.py` is the sole active,
immutable portal registry. Together with the fixed `CATALOGUE_PORTAL_IDS`
tuple, it defines exactly seven canonical portal IDs and their public catalogue
locations. The catalogue CLI observes public metadata using anonymous,
read-only GET requests. This does not establish that every underlying dataset
resource is anonymously accessible or redistributable.

Run sync explicitly from the repository root. The web UI never triggers it:

```powershell
$env:PYTHONPATH = "backend"
python -m app.catalogue_cli sync --portal all
python -m app.catalogue_cli sync --portal nged
```

The catalogue registry defaults to
`data/cache/catalogue/registry.sqlite3`; immutable JSON snapshots default to
`data/snapshots/catalogues/`. Override these local locations with
`FLEXCOMPASS_CATALOGUE_DB_PATH` and
`FLEXCOMPASS_CATALOGUE_SNAPSHOT_DIR`. These are path settings only: do not put
credentials or other secrets in them. Generated databases, snapshots, caches,
review queues, and reports are Git-ignored. Compare two local snapshots or
inspect the unresolved evidence queue with:

```powershell
python -m app.catalogue_cli diff --before data/snapshots/catalogues/20260715T120000.000000Z/nged.json --after data/snapshots/catalogues/20260716T120000.000000Z/nged.json
python -m app.catalogue_cli review-queue --format json
```

After a local sync, the API serves exactly these eight versioned GET-only
catalogue routes:

- `/api/v1/catalogue/portals`
- `/api/v1/catalogue/portals/{portal_id}`
- `/api/v1/catalogue/datasets`
- `/api/v1/catalogue/datasets/{dataset_ref}`
- `/api/v1/catalogue/datasets/{dataset_ref}/resources`
- `/api/v1/catalogue/datasets/{dataset_ref}/evidence`
- `/api/v1/catalogue/datasets/{dataset_ref}/assessments`
- `/api/v1/catalogue/observations`

List routes use bounded pagination: the default limit is 50, the allowed range
is 1 to 200, and offsets are non-negative. Dataset list filters are evaluated
server-side for portal, text, lifecycle, publication pattern, access status,
and maintenance state; observation history can be filtered by portal and
status. A `dataset_ref` is an opaque, portal-scoped URL-safe identifier. Clients
must use the returned value unchanged and URI-encode it when placing it in a
path; its internal representation is not a public contract.

Portal coverage separates the newest durable refresh attempt from the newest
complete observation and the last valid complete snapshot. A failed attempt is
recorded without creating an observation or replacing last-valid evidence. A
partial attempt and snapshot are retained, but partial evidence does not become
the last-valid API dataset source. Complete snapshots are validated before use;
if the newest complete snapshot is invalid, the repository may fall back to an
older valid complete snapshot and reports the portal as degraded. If no valid
complete snapshot exists, catalogue datasets are unavailable rather than read
from mutable rows, legacy seeds, or a partial snapshot.

The portal due state is based on a 168-hour FlexCompass operational review
window from the latest attempt and is reported as `current`, `overdue`, or
`never_attempted`. It is a local review policy, not a claim about publisher
cadence or live freshness.

The UI keeps `Research Overview` as the default top-level tab. `Catalogue
Observatory` contains `Coverage` and `Datasets` tabs for the seven portals,
server-filtered datasets, safe detail, and portal observation history.
`Synthetic Demo` remains separately labelled and uses no current portal data.
Unknown, restricted, unreachable, failed, partial, archival, superseded, and
snapshot states are rendered as visible text rather than colour alone.

Maintenance remains unknown unless public evidence explicitly establishes an
active lifecycle and a defensible freshness clock. Catalogue-edit timestamps do
not stand in for data/release freshness, and the adapters do not infer missing
lifecycle or access facts.

See [public data sources](docs/public-data-sources.md) for portal-specific scope,
licence cautions, and limitations.

## Current product boundary

Catalogue metadata is discovery and evidence about public datasets; it is not
analytical ingestion and does not establish data freshness, analytical
readiness, eligibility, or commercial value. The API exposes safe declared
licence and attribution metadata where present, but that is not licence
verification or relicensing. Canonical `raw_record` values, raw pages, request
URLs, local paths, authentication setting names, raw errors, and reviewer
identity remain internal evidence and are not exposed by the catalogue API.

The FastAPI surface provides read-only catalogue metadata alongside read-only
SSEN historical-outage queries after their explicit local syncs; neither API
nor web surface starts catalogue or analytical ingestion, drift execution,
bidding, dispatch, or asset control, and FlexCompass does not provide commercial
advice.
No verified canonical flexibility-signal or zone dataset is exposed in this
release. The hidden legacy `/api/portal/datasets` surface returns `410 Gone` for
`GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`, and `OPTIONS`, never reads
legacy rows, and is absent from OpenAPI.

## Verification

```powershell
python -m pytest
python -m ruff check .
python scripts\check_public_boundary.py .
cd frontend
npm run build
```

## Project layout

- `backend/app/`: read-only catalogue CLI, SSEN outage sync/query CLI and API,
  catalogue API, research-status and synthetic-demo API, public portal adapters,
  storage, models, matching, and reports.
- `backend/tests/`: API and unit tests using disposable data and explicit fixtures.
- `frontend/`: research-status overview, read-only catalogue observatory, and
  explicitly synthetic demonstration.
- `data/seed/`: explicitly synthetic demonstration portfolios only.
- `docs/`: public data model, postcode-matching notes, and source register.
- `scripts/`: repository privacy and generated-artifact checks.

## Licence and source attribution

FlexCompass source code is available under the [MIT License](LICENSE). That
licence does not relicense third-party datasets. Check each dataset's terms and
attribution requirements before downloading, redistributing, or publishing
derived outputs.

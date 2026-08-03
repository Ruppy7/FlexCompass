# FlexCompass

FlexCompass is an independent open-source research toolkit for exploring public
data about Great Britain's electricity networks and local flexibility markets.
It bridges energy-domain research with reproducible Python data pipelines, a
FastAPI research API, and a small Next.js interface.

The active public-data workflows are the anonymous, read-only seven-portal
catalogue CLI and the reviewed SSEN historical-HV outage sync and query path.

The local API exposes verified SSEN outage evidence after a user runs the local
sync. The Next.js application remains a research-status overview and an
explicitly synthetic demonstration; it does not expose the catalogue registry
or SSEN records.

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

`CATALOGUE_PORTALS` in `backend/app/catalogue_models.py` is the sole active
portal registry. It defines the seven canonical portal IDs and catalogue API
bases used by the CLI. The catalogue intelligence workflow observes their
public metadata using anonymous, read-only GET requests. It does not establish
that every underlying dataset resource is anonymously accessible or
redistributable.

Run these commands from the `backend/` directory. Sync every configured portal
or select one:

```powershell
cd backend
python -m app.catalogue_cli sync --portal all
python -m app.catalogue_cli sync --portal nged
```

The default SQLite registry, JSON snapshots, cache, and review queue are local,
Git-ignored outputs under `../data/cache/catalogue/` and
`../data/snapshots/catalogues/`. Compare two local snapshots or inspect the
unresolved evidence queue with:

```powershell
python -m app.catalogue_cli diff --before ../data/snapshots/catalogues/20260715T120000.000000Z/nged.json --after ../data/snapshots/catalogues/20260716T120000.000000Z/nged.json
python -m app.catalogue_cli review-queue --format json
```

Maintenance remains unknown unless public evidence explicitly establishes an
active lifecycle and a defensible freshness clock. Catalogue-edit timestamps do
not stand in for data/release freshness, and the adapters do not infer missing
lifecycle or access facts.

See [public data sources](docs/public-data-sources.md) for portal-specific scope,
licence cautions, and limitations.

## Current product boundary

The catalogue registry is available through the local CLI only. The FastAPI
surface provides read-only SSEN historical-outage queries after explicit local
sync; neither API nor web surface starts catalogue or analytical ingestion,
drift execution, bidding, dispatch, or asset control. No verified canonical
flexibility-signal or zone dataset is exposed in this release.

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
  research-status and synthetic-demo API, public portal adapters, storage,
  models, matching, and reports.
- `backend/tests/`: API and unit tests using disposable data and explicit fixtures.
- `frontend/`: research-status overview and explicitly synthetic demonstration.
- `data/seed/`: explicitly synthetic demonstration portfolios only.
- `docs/`: public data model, postcode-matching notes, and source register.
- `scripts/`: repository privacy and generated-artifact checks.

## Licence and source attribution

FlexCompass source code is available under the [MIT License](LICENSE). That
licence does not relicense third-party datasets. Check each dataset's terms and
attribution requirements before downloading, redistributing, or publishing
derived outputs.

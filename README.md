# FlexCompass

FlexCompass is an independent open-source research toolkit for exploring public
data about Great Britain's electricity networks and local flexibility markets.
It bridges energy-domain research with reproducible Python data pipelines, a
FastAPI research API, and a small Next.js interface.

The active public-data workflow is the anonymous, read-only seven-portal
catalogue CLI.

The web application exposes a research-status overview and an explicitly
synthetic demonstration. It does not yet expose the catalogue registry or
verified analytical portal records.

The legacy generic portal ingestors and browser-triggered mutation routes were
retired because they lacked accepted source contracts and end-to-end
provenance.

The repository also contains SQLite storage, provenance-preserving models,
postcode and geometry matching, data-quality utilities, synthetic portfolio
examples, and directional report generation.

This is a research project, not a product. It does not bid, dispatch or control
assets, establish eligibility, forecast revenue, or provide commercial advice.
Any scores are heuristic and directional.

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

The catalogue registry is available through the local CLI only. The FastAPI and
web surfaces do not provide catalogue sync, analytical portal ingestion, drift
execution, bidding, dispatch, or asset control. No verified canonical
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

- `backend/app/`: research-status and synthetic-demo API, read-only catalogue
  CLI, public portal adapters, storage, models, matching, and reports.
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

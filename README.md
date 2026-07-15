# FlexCompass

FlexCompass is an independent open-source research toolkit for exploring public
data about Great Britain's electricity networks and local flexibility markets.
It bridges energy-domain research with reproducible Python data pipelines, a
FastAPI research API, and a small Next.js interface.

The repository currently provides public catalogue ingestion foundations for
NGED, SP Energy Networks, Electricity North West, and SSEN; SQLite storage;
provenance-preserving normalisation models; postcode and geometry matching;
data-quality utilities; synthetic portfolio examples; and directional report
generation.

This is a research project, not a product. It does not bid, dispatch or control
assets, establish eligibility, forecast revenue, or provide commercial advice.
Any scores are heuristic and directional.

## Data status

The checked-in `flex_zones.json`, `flex_signals.json`, and `market_rules.json`
files are intentionally empty. FlexCompass does not publish hand-curated claims
as if they were current market facts. Normalised records should be created from
public portal responses only after their schemas, provenance, licence, and
limitations are verified.

Downloaded records and generated SQLite databases stay local and are ignored by
Git. See [public data sources](docs/public-data-sources.md) for the source
register and verification status.

## Quick start

Python 3.11+ and Node.js 18+ are expected.

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

## Public ingestion

Run from the repository root after adding any public portal tokens to `.env`:

```powershell
python -m backend.app.ingest --nged
python -m backend.app.ingest --spen
python -m backend.app.ingest --enwl
python -m backend.app.ingest
```

The final command attempts all four implemented portal pipelines, including
SSEN. Portal availability, account requirements, dataset identifiers, and
schemas can change; inspect the output and validate the resulting records.

To regenerate a local database from checked-in metadata and empty analytical
seeds:

```powershell
python -m backend.app.db_seed
```

## Verification

```powershell
python -m pytest
python -m ruff check .
python scripts\check_public_boundary.py .
cd frontend
npm run build
```

## Project layout

- `backend/app/`: API, public portal clients, storage, models, matching, reports.
- `backend/tests/`: API and unit tests using disposable data and explicit fixtures.
- `frontend/`: public-data explorer and synthetic analysis interface.
- `data/seed/`: conservative source metadata, empty normalised datasets, and
  synthetic examples.
- `docs/`: data model, matching notes, public source register, and backlog.
- `scripts/`: repository privacy and generated-artifact checks.

## Licence and source attribution

FlexCompass source code is available under the [MIT License](LICENSE). That
licence does not relicense third-party datasets. Check each dataset's terms and
attribution requirements before downloading, redistributing, or publishing
derived outputs.

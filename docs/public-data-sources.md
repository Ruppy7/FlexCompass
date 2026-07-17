# Public data source register

This register identifies public portals supported or planned by FlexCompass. A
portal being public does not mean every resource has the same licence or access
conditions. Dataset-level terms must be checked before redistribution. Portal
and catalogue access was last checked on 15 July 2026.

| Owner | Official portal | Public catalogue API | Catalogue authentication | Licence status | Current limitation |
|---|---|---|---|---|---|
| National Grid Electricity Distribution | https://connecteddata.nationalgrid.co.uk | `https://connecteddata.nationalgrid.co.uk/api/3/action` (CKAN) | None observed | Verify per dataset; many catalogue entries do not declare a licence | Dataset identifiers, resource licences, and schemas need contract tests |
| SP Energy Networks | https://spenergynetworks.opendatasoft.com | `https://spenergynetworks.opendatasoft.com/api/explore/v2.1` | None observed | Verify per dataset; some catalogue entries do not declare a licence | Record visibility, resource coverage, and update schedules vary |
| SP Electricity North West | https://electricitynorthwest.opendatasoft.com | `https://electricitynorthwest.opendatasoft.com/api/explore/v2.1` | None observed | Verify per dataset | Record visibility and download conditions vary by resource |
| Scottish and Southern Electricity Networks | https://data.ssen.co.uk | `https://data-api.ssen.co.uk/api/3/action` (CKAN) | None observed | Verify per dataset | Resource formats, history, and schemas vary |
| UK Power Networks | https://ukpowernetworks.opendatasoft.com | `https://ukpowernetworks.opendatasoft.com/api/explore/v2.1` | None observed | Verify per dataset | Some datasets publish metadata or attachments without public record queries |
| Northern Powergrid | https://northernpowergrid.opendatasoft.com | `https://northernpowergrid.opendatasoft.com/api/explore/v2.1` | None observed | Verify per dataset | Some network asset datasets have separate access-request conditions |
| National Energy System Operator | https://www.neso.energy/data-portal | `https://api.neso.energy/api/3/action` (CKAN) | None observed; an account is optional for subscriptions and favourites | Verify per dataset; the current catalogue names the NESO Open Data Licence | National and transmission-system data is context, not a substitute for DSO outage or local-flexibility evidence |

Anonymous catalogue access does not prove that every dataset resource is
anonymous or redistributable. The repository stores curated catalogue metadata
only. Generated snapshots, SQLite databases, caches, queues, and reports are
ignored/local outputs and must not be committed.

## Catalogue intelligence workflow

All commands run from the `backend/` working directory using the project venv.

### Sync

Fetch public metadata with anonymous read-only GET requests:

```bash
python -m app.catalogue_cli sync --portal all
python -m app.catalogue_cli sync --portal nged
```

Outputs (all git-ignored): SQLite registry at
`../data/cache/catalogue/registry.sqlite3`, JSON snapshots at
`../data/snapshots/catalogues/<timestamp>/<portal>.json`, and review queue at
`../data/cache/catalogue/review-queue.json`. Snapshots are atomic and immutable.
Failed portals do not alter the registry. Partial observations update the
registry conservatively without erasing missing source facts. Complete
observations clear withdrawn current facts and reconcile obsolete resources and
classification evidence for the datasets they contain.

### Diff

Compare two local snapshots:

```bash
python -m app.catalogue_cli diff \
  --before ../data/snapshots/catalogues/20260715T120000.000000Z/nged.json \
  --after  ../data/snapshots/catalogues/20260716T120000.000000Z/nged.json
```

Changes: `dataset_added`, `dataset_removed`, `metadata_changed`,
`source_evidence_changed`, `resources_replaced`, `access_changed`. Snapshot
schema, manifest semantics, unique usable counts, and content hashes are
validated before comparison. A partial snapshot never produces a definitive
dataset-removal claim.

### Review queue

Print unresolved evidence items:

```bash
python -m app.catalogue_cli review-queue --format json
```

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

Every record retains `source_dataset_id`, `raw_record`, and `observed_at`.
Content hashes (SHA-256 of the redacted source snapshot, separate from
classifier assessments) support deduplication. Benign public URL query
parameters are retained. All
artifacts are redacted of: authentication keys (`authorization`, `token`,
`api_key`, `secret`, `password`, `credential`, `cookie`), inline credential
patterns, Basic/Bearer values, private-host URLs, credential-bearing URLs, and
common signed-URL credentials/signatures/security tokens. Benign URL fragments
are retained; credential-bearing fragment pairs are removed selectively.

## Limitations

Catalogue metadata is not analytical ingestion, eligibility assessment,
bidding/dispatch/asset-control advice, forecasting, or commercial advice.
Counts and metadata are dated observations, not stable facts. Licence and
attribution must be verified before redistributing source data.

Live portal tests are opt-in via `FLEXCOMPASS_LIVE_PORTAL_TESTS=1`; seven
parametrized cases are skipped by default with zero network calls. Enabled cases
require complete observations and an exact match between expected count and
unique usable dataset IDs.
